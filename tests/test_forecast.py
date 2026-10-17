"""Tests for the forecast agent. No network: requests.get is faked, the clock is fixed.

Run from the smogshield folder:  python -m unittest discover tests -v
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from agents import analysis, forecast  # noqa: E402
from schemas import Forecast, ForecastPoint  # noqa: E402

OFFSET = 5 * 3600                                          # Pakistan, UTC+5
NOW = datetime(2026, 10, 17, 10, 30, tzinfo=timezone.utc)  # 15:30 local
DAY0 = datetime(2026, 10, 17)                              # local midnight, like the real API


def api_response(values: list, offset: int = OFFSET) -> dict:
    """A response shaped like the real one: local times from 00:00 today, one value per hour."""
    times = [(DAY0 + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(len(values))]
    return {
        "utc_offset_seconds": offset,
        "timezone": "Asia/Karachi",
        "hourly_units": {"time": "iso8601", "pm2_5": "μg/m³", "pm10": "μg/m³"},
        "hourly": {"time": times, "pm2_5": values, "pm10": [v if v is None else v * 2 for v in values]
                   if all(isinstance(v, (int, float)) or v is None for v in values) else values},
    }


def fake_response(body: dict, status: int = 200) -> mock.Mock:
    return mock.Mock(status_code=status, ok=status < 400, json=lambda: body, text=str(body))


STEADY = api_response([float(20 + i % 10) for i in range(96)])   # 96 hours, like forecast_days=4


class ForecastTestCase(unittest.TestCase):
    def setUp(self):
        drop = {"FORECAST_CACHE_MINUTES", "USE_MOCK", "MOCK_SCENARIO", "MONITOR_CITY"}
        env_patch = mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k not in drop}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        forecast._cache.clear()


class CleanSeriesTest(ForecastTestCase):
    def test_converts_to_utc_rounds_and_orders(self):
        data = api_response([10.04, 11.06, 12.0])
        data["hourly"]["time"].reverse()          # shuffled input
        data["hourly"]["pm2_5"].reverse()
        points = forecast.clean_series(data)["points"]
        self.assertEqual([p["time"] for p in points],
                         ["2026-10-16T19:00:00+00:00", "2026-10-16T20:00:00+00:00", "2026-10-16T21:00:00+00:00"])
        self.assertEqual([p["pm25"] for p in points], [10.0, 11.1, 12.0])

    def test_rejects_nulls_negatives_nan_and_text(self):
        data = api_response([10.0, None, -3.0, float("nan"), "n/a", 15.0])
        self.assertEqual([p["pm25"] for p in forecast.clean_series(data)["points"]], [10.0, 15.0])

    def test_all_missing_raises(self):
        with self.assertRaises(ValueError):
            forecast.clean_series(api_response([None, None, None]))

    def test_unexpected_unit_raises(self):
        data = api_response([10.0])
        data["hourly_units"]["pm2_5"] = "ppm"
        with self.assertRaises(ValueError):
            forecast.clean_series(data)

    def test_keeps_the_offset(self):
        self.assertEqual(forecast.clean_series(api_response([1.0]))["offset"], OFFSET)


class HourlyPointsTest(ForecastTestCase):
    def test_next_24_hours_from_the_current_hour(self):
        points = forecast.hourly_points(forecast.clean_series(STEADY)["points"], NOW)
        self.assertEqual(len(points), 24)
        self.assertEqual(points[0]["time"], "2026-10-17T10:00:00+00:00")   # the current hour, 15:00 local
        self.assertEqual([p["hours_ahead"] for p in points], list(range(24)))
        self.assertEqual(points, sorted(points, key=lambda p: p["time"]))

    def test_aqi_matches_the_current_reading_formula(self):
        for p in forecast.hourly_points(forecast.clean_series(STEADY)["points"], NOW):
            self.assertEqual((p["aqi"], p["level"]), analysis.pm25_to_aqi(p["pm25"]))
            self.assertEqual(set(p), set(ForecastPoint.__annotations__))

    def test_confidence_labels(self):
        cases = {0: "high", 6: "high", 6.5: "medium", 7: "medium", 24: "medium", 24.5: "low", 48: "low"}
        for hours, expected in cases.items():
            with self.subTest(hours=hours):
                self.assertEqual(forecast.confidence_for(hours), expected)
        labels = [p["confidence"] for p in forecast.hourly_points(forecast.clean_series(STEADY)["points"], NOW)]
        self.assertEqual(labels, ["high"] * 7 + ["medium"] * 17)


class FetchTest(ForecastTestCase):
    def test_request_parameters(self):
        with mock.patch.object(forecast.requests, "get", return_value=fake_response(STEADY)) as get:
            forecast.fetch_series("Lahore")
        params = get.call_args.kwargs["params"]
        self.assertEqual((params["hourly"], params["forecast_days"], params["timezone"], params["timeformat"]),
                         ("pm2_5,pm10", 4, "auto", "iso8601"))
        self.assertEqual(get.call_args.kwargs["timeout"], forecast.TIMEOUT_SECONDS)

    def test_cached_for_30_minutes_per_city(self):
        with mock.patch.object(forecast.requests, "get", return_value=fake_response(STEADY)) as get, \
                mock.patch.object(forecast.time, "monotonic", return_value=1000.0) as clock:
            forecast.fetch_series("Lahore")
            clock.return_value = 1000.0 + 29 * 60
            forecast.fetch_series("Lahore")
            self.assertEqual(get.call_count, 1)
            forecast.fetch_series("Karachi")                 # another city: its own entry
            self.assertEqual(get.call_count, 2)
            clock.return_value = 1000.0 + 30 * 60
            forecast.fetch_series("Lahore")                  # expired
            self.assertEqual(get.call_count, 3)

    def test_cache_env_var(self):
        os.environ["FORECAST_CACHE_MINUTES"] = "0"
        with mock.patch.object(forecast.requests, "get", return_value=fake_response(STEADY)) as get:
            forecast.fetch_series("Lahore")
            forecast.fetch_series("Lahore")
        self.assertEqual(get.call_count, 2)
        os.environ["FORECAST_CACHE_MINUTES"] = "soon"
        self.assertEqual(forecast._cache_seconds(), forecast.DEFAULT_CACHE_MINUTES * 60)

    def test_failures_are_not_cached(self):
        with mock.patch.object(forecast.requests, "get", side_effect=requests.ConnectionError("offline")):
            with self.assertRaises(requests.ConnectionError):
                forecast.fetch_series("Lahore")
        with mock.patch.object(forecast.requests, "get", return_value=fake_response(STEADY)):
            self.assertTrue(forecast.fetch_series("Lahore")["points"])

    def test_cached_series_cannot_be_changed_by_callers(self):
        with mock.patch.object(forecast.requests, "get", return_value=fake_response(STEADY)):
            forecast.fetch_series("Lahore")["points"][0]["pm25"] = -1
            self.assertNotEqual(forecast.fetch_series("Lahore")["points"][0]["pm25"], -1)


class BuildTest(ForecastTestCase):
    def test_live_forecast_matches_schema(self):
        with mock.patch.object(forecast.requests, "get", return_value=fake_response(STEADY)):
            result = forecast.build_forecast("Lahore", now=NOW)
        self.assertEqual(set(result), set(Forecast.__annotations__))
        self.assertEqual((result["location"], result["source"], result["is_model_estimate"]), ("Lahore", "live", True))
        self.assertEqual(len(result["hourly"]), 24)
        self.assertIn("estimate", result["note"])

    def test_failures_never_raise(self):
        for behaviour in ({"side_effect": requests.Timeout("slow")},
                          {"side_effect": requests.ConnectionError("offline")},
                          {"return_value": fake_response({"error": True, "reason": "bad"}, 400)},
                          {"return_value": fake_response(api_response([None] * 96))}):
            with self.subTest(behaviour=behaviour), mock.patch.object(forecast.requests, "get", **behaviour):
                result = forecast.build_forecast("Lahore", now=NOW)
                self.assertEqual(set(result), set(Forecast.__annotations__))
                self.assertEqual(result["source"], "mock")

    def test_unknown_city_never_raises(self):
        with mock.patch.object(forecast.requests, "get", side_effect=AssertionError("network called")):
            self.assertEqual(forecast.build_forecast("Atlantis", now=NOW)["location"], "Atlantis")

    def test_run_uses_the_monitored_city(self):
        state = {"readings": [{"location": "karachi", "timestamp": "x", "pm25": 30.0, "pm10": None, "source": "live"}]}
        with mock.patch.object(forecast.requests, "get", return_value=fake_response(STEADY)):
            result = forecast.run(state)
        self.assertEqual(set(result), {"forecast"})
        self.assertEqual(result["forecast"]["location"], "Karachi")


if __name__ == "__main__":
    unittest.main()
