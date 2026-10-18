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


HOUR0 = NOW.replace(minute=0)   # 10:00 UTC, the current hour


def points(values: list[float], start_ahead: int = 0) -> list[dict]:
    """Forecast points for consecutive hours from the current hour."""
    out = []
    for i, v in enumerate(values):
        ahead = start_ahead + i
        aqi, level = analysis.pm25_to_aqi(v)
        out.append({"time": (HOUR0 + timedelta(hours=ahead)).isoformat(), "hours_ahead": ahead, "pm25": float(v),
                    "aqi": aqi, "level": level, "confidence": forecast.confidence_for(ahead)})
    return out


class WindowSummaryTest(unittest.TestCase):
    def test_peak_and_when(self):
        result = forecast.summarize_window(points([20, 25, 60, 30, 30, 30] + [10] * 18), 6)
        self.assertEqual(result["peak_aqi"], analysis.pm25_to_aqi(60)[0])
        self.assertEqual(result["peak_time"], (HOUR0 + timedelta(hours=2)).isoformat())
        self.assertEqual(result["peak_level"], "moderate")
        self.assertEqual(result["hours"], 6)

    def test_equal_peaks_report_the_earliest(self):
        result = forecast.summarize_window(points([40, 80, 30, 80]), 6)
        self.assertEqual(result["peak_time"], (HOUR0 + timedelta(hours=1)).isoformat())

    def test_window_only_uses_its_hours(self):
        values = [20] * 6 + [300] * 18           # the bad air arrives after 6 hours
        self.assertEqual(forecast.summarize_window(points(values), 6)["peak_level"], "satisfactory")
        self.assertEqual(forecast.summarize_window(points(values), 24)["peak_level"], "severe")

    def test_typical_level_is_the_level_of_the_average(self):
        result = forecast.summarize_window(points([10, 10, 10, 10, 10, 100]), 6)   # average 25
        self.assertEqual(result["typical_level"], analysis.pm25_to_aqi(25)[1])

    def test_trends(self):
        cases = {
            "worsening": [20, 20, 25, 28, 30, 30],     # +10, more than 10% and 3 µg/m³
            "improving": [100, 100, 95, 90, 80, 80],   # -20
            "stable": [50, 52, 49, 51, 51, 53],        # +1
        }
        for expected, values in cases.items():
            with self.subTest(trend=expected):
                self.assertEqual(forecast.summarize_window(points(values), 6)["trend"], expected)

    def test_small_change_in_clean_air_is_stable(self):
        self.assertEqual(forecast.summarize_window(points([4, 4, 5, 5, 6, 6]), 6)["trend"], "stable")  # +2 < 3

    def test_confidence_per_window(self):
        values = list(range(10, 34))
        self.assertEqual(forecast.summarize_window(points(values), 6)["confidence"], "high")
        self.assertEqual(forecast.summarize_window(points(values), 24)["confidence"], "medium")

    def test_no_points(self):
        self.assertIsNone(forecast.summarize_window([], 6))


class BestTimeTest(unittest.TestCase):
    def test_lowest_two_hour_window(self):
        values = [50, 45, 40, 30, 25, 10, 12, 30, 40]
        result = forecast.best_time(points(values))
        self.assertEqual(result["start"], (HOUR0 + timedelta(hours=5)).isoformat())
        self.assertEqual(result["end"], (HOUR0 + timedelta(hours=7)).isoformat())   # two hours, end exclusive
        self.assertEqual(result["avg_pm25"], 11.0)
        self.assertEqual((result["aqi"], result["level"]), analysis.pm25_to_aqi(11.0))

    def test_tie_takes_the_earliest(self):
        result = forecast.best_time(points([30, 10, 10, 30, 10, 10]))
        self.assertEqual(result["start"], (HOUR0 + timedelta(hours=1)).isoformat())

    def test_skips_windows_across_a_gap(self):
        pts = points([30, 5]) + points([5, 30], start_ahead=5)   # hours 0,1 then 5,6: 1 and 5 are not adjacent
        result = forecast.best_time(pts)
        self.assertEqual(result["avg_pm25"], 17.5)

    def test_too_few_points(self):
        self.assertIsNone(forecast.best_time(points([10])))
        self.assertIsNone(forecast.best_time([]))


class OutlookTest(unittest.TestCase):
    def series(self, values_by_utc_hour: dict) -> list[dict]:
        return [{"time": (HOUR0 + timedelta(hours=h)).isoformat(), "pm25": float(v)} for h, v in sorted(values_by_utc_hour.items())]

    def test_one_peak_per_local_day(self):
        # now is 15:30 local on Oct 17; UTC hour 14 = 19:00 local today, UTC hour 17 = 08:00 local Oct 18
        result = forecast.daily_outlook(self.series({0: 40, 4: 200, 8: 60, 17: 300, 30: 20}), OFFSET, NOW)
        self.assertEqual([d["date"] for d in result], ["2026-10-17", "2026-10-18"])
        self.assertEqual(result[0]["peak_aqi"], analysis.pm25_to_aqi(200)[0])
        self.assertEqual(result[1]["peak_level"], "severe")
        self.assertEqual((result[0]["confidence"], result[1]["confidence"]), ("high", "medium"))

    def test_past_hours_are_ignored(self):
        result = forecast.daily_outlook(self.series({-3: 500, 0: 20}), OFFSET, NOW)
        self.assertEqual(result[0]["peak_aqi"], analysis.pm25_to_aqi(20)[0])

    def test_four_days_from_a_real_shaped_response(self):
        series = forecast.clean_series(STEADY)
        result = forecast.daily_outlook(series["points"], series["offset"], NOW)
        self.assertEqual([d["date"] for d in result], ["2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20"])
        # each day's confidence follows its peak hour: today's is 4 h ahead, tomorrow's (09:00 local) 18 h
        self.assertEqual([d["confidence"] for d in result], ["high", "medium", "low", "low"])


MOCK_READINGS = __import__("json").loads((Path(__file__).parent.parent / "data" / "mock_readings.json").read_text(encoding="utf-8"))
UNHEALTHY_OR_WORSE = {"poor", "very_poor", "severe"}


def reading(pm25: float, source: str = "mock", city: str = "Lahore") -> list[dict]:
    return [{"location": city, "timestamp": NOW.isoformat(), "pm25": pm25, "pm10": None, "source": source}]


class MockForecastTest(ForecastTestCase):
    def scenario_forecasts(self, scenario: str):
        """The scripted forecast from every reading this scenario can produce."""
        for pm25 in MOCK_READINGS["scenarios"][scenario]["pm25"]:
            yield pm25, forecast.mock_forecast("Lahore", float(pm25), scenario=scenario, now=NOW)

    def test_every_scenario_has_a_scripted_forecast(self):
        self.assertEqual(set(forecast._mock_curves()), set(MOCK_READINGS["scenarios"]))

    def test_forecast_starts_at_the_current_reading(self):
        for scenario in MOCK_READINGS["scenarios"]:
            for pm25, result in self.scenario_forecasts(scenario):
                with self.subTest(scenario=scenario, pm25=pm25):
                    self.assertEqual(result["hourly"][0]["pm25"], round(float(pm25), 1))
                    self.assertEqual((result["source"], result["is_model_estimate"]), ("mock", True))
                    self.assertEqual(set(result), set(Forecast.__annotations__))

    def test_each_scenario_tells_its_story(self):
        checks = {
            "good": lambda f, now: all(p["level"] == "good" for p in f["hourly"]),
            "satisfactory": lambda f, now: f["next_6h"]["peak_level"] not in UNHEALTHY_OR_WORSE
                                       and f["next_24h"]["peak_aqi"] > f["hourly"][0]["aqi"],          # worse into the evening
            "moderate": lambda f, now: (
                f["next_6h"]["peak_level"] in UNHEALTHY_OR_WORSE
                and any(p["pm25"] >= 125.5 for p in f["hourly"][:7])
            ),  # predictive-alert demo crosses into Poor within 6 hours
            "poor": lambda f, now: f["next_24h"]["trend"] == "improving",
            "very_poor": lambda f, now: f["next_6h"]["trend"] == "worsening" and f["next_24h"]["trend"] == "improving",
            "severe": lambda f, now: f["next_24h"]["trend"] == "improving"
                                        and f["outlook"][2]["peak_aqi"] < f["hourly"][0]["aqi"],          # better in 1-2 days
            "spike": lambda f, now: f["next_24h"]["trend"] == "improving"
                                    and f["hourly"][8]["pm25"] < f["hourly"][0]["pm25"],                  # easing after a few hours
        }
        self.assertEqual(set(checks), set(MOCK_READINGS["scenarios"]))
        for scenario, check in checks.items():
            for pm25, result in self.scenario_forecasts(scenario):
                with self.subTest(scenario=scenario, pm25=pm25):
                    self.assertTrue(check(result, NOW))

    def test_covers_the_rest_of_today_and_three_days(self):
        result = forecast.mock_forecast("Lahore", 100.0, scenario="poor", now=NOW)
        self.assertEqual([d["date"] for d in result["outlook"]], ["2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20"])
        self.assertEqual(len(result["hourly"]), 24)

    def test_interpolation(self):
        curve = [[0, 1.0], [4, 2.0], [8, 1.0]]
        self.assertEqual([forecast._interpolate(curve, h) for h in (0, 2, 4, 6, 8, 20)], [1.0, 1.5, 2.0, 1.5, 1.0, 1.0])


class MockSwitchTest(ForecastTestCase):
    def test_mock_scenario_env_drives_the_forecast(self):
        os.environ["MOCK_SCENARIO"] = "severe"
        with mock.patch.object(forecast.requests, "get", side_effect=AssertionError("network called")):
            result = forecast.build_forecast("Lahore", now=NOW, readings=reading(300.0))
        self.assertEqual(result["source"], "mock")
        self.assertEqual(result["next_24h"]["trend"], "improving")   # the severe curve

    def test_use_mock_env_drives_the_forecast(self):
        os.environ["USE_MOCK"] = "true"
        with mock.patch.object(forecast.requests, "get", side_effect=AssertionError("network called")):
            self.assertEqual(forecast.build_forecast("Lahore", now=NOW, readings=reading(30.0))["source"], "mock")

    def test_mock_reading_gets_a_mock_forecast(self):
        # the monitor already fell back to mock data: keep the story consistent, no network
        with mock.patch.object(forecast.requests, "get", side_effect=AssertionError("network called")):
            self.assertEqual(forecast.build_forecast("Lahore", now=NOW, readings=reading(30.0, source="mock"))["source"], "mock")

    def test_live_reading_gets_a_live_forecast(self):
        with mock.patch.object(forecast.requests, "get", return_value=fake_response(STEADY)):
            self.assertEqual(forecast.build_forecast("Lahore", now=NOW, readings=reading(30.0, source="live"))["source"], "live")

    def test_live_failure_falls_back_to_the_citys_scenario(self):
        with mock.patch.object(forecast.requests, "get", side_effect=requests.ConnectionError("offline")), \
                self.assertLogs(forecast.log, "WARNING"):
            result = forecast.build_forecast("Lahore", now=NOW, readings=reading(80.0, source="live"))
        self.assertEqual((result["source"], result["note"]), ("mock", forecast.MOCK_NOTE))
        self.assertEqual(result["hourly"][0]["pm25"], 80.0)
        self.assertIsNotNone(result["next_6h"])

    def test_missing_or_broken_file_uses_a_flat_forecast(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            for content in (None, "{oops", '{"curves": {"good": [[4, 1], [0, 1]]}}'):
                path = Path(tmp) / "mock_forecasts.json"
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(content, encoding="utf-8")
                with self.subTest(content=content), mock.patch.object(forecast, "MOCK_FILE", path):
                    result = forecast.mock_forecast("Lahore", 40.0, scenario="good", now=NOW)
                    self.assertTrue(all(p["pm25"] == 40.0 for p in result["hourly"]))

    def test_no_reading_uses_the_base_level(self):
        result = forecast.mock_forecast("Lahore", None, scenario="poor", now=NOW)
        self.assertEqual(result["hourly"][0]["pm25"], forecast.MOCK_BASE_PM25)

    def test_bad_readings_never_raise(self):
        for readings in (None, [], [{}], [{"pm25": "abc", "source": "mock"}], "nonsense"):
            with self.subTest(readings=readings), mock.patch.object(forecast.requests, "get",
                                                                    side_effect=requests.ConnectionError("x")):
                self.assertEqual(set(forecast.build_forecast("Lahore", now=NOW, readings=readings)),
                                 set(Forecast.__annotations__))


class BuildTest(ForecastTestCase):
    def test_live_forecast_has_every_summary(self):
        with mock.patch.object(forecast.requests, "get", return_value=fake_response(STEADY)):
            result = forecast.build_forecast("Lahore", now=NOW)
        self.assertEqual((result["next_6h"]["hours"], result["next_24h"]["hours"]), (6, 24))
        self.assertIsNotNone(result["best_time"])
        self.assertEqual(len(result["outlook"]), 4)

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
