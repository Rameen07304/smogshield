"""Tests for the monitor agent. No network needed: requests.get is faked.

Run from the smogshield folder:  python -m unittest discover tests -v
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from agents import analysis, monitor  # noqa: E402
from schemas import Reading  # noqa: E402

# Real Open-Meteo response for Lahore, captured 2026-10-17
LAHORE_RESPONSE = {
    "latitude": 31.599998, "longitude": 74.3, "utc_offset_seconds": 18000,
    "timezone": "Asia/Karachi",
    "current_units": {"time": "iso8601", "interval": "seconds", "pm10": "μg/m³", "pm2_5": "μg/m³"},
    "current": {"time": "2026-10-17T11:00", "interval": 3600, "pm10": 30.6, "pm2_5": 23.5},
}


def fake_response(body: dict, status: int = 200) -> mock.Mock:
    return mock.Mock(status_code=status, ok=status < 400, json=lambda: body, text=str(body))


def assert_valid_reading(test: unittest.TestCase, reading: dict) -> None:
    """Output format: exactly the schema keys, no None where it's required."""
    test.assertEqual(set(reading), set(Reading.__annotations__))
    test.assertIsInstance(reading["pm25"], float)
    test.assertGreaterEqual(reading["pm25"], 0)
    test.assertTrue(reading["pm10"] is None or isinstance(reading["pm10"], float))
    test.assertTrue(reading["location"])
    test.assertTrue(reading["timestamp"].endswith("+00:00"), reading["timestamp"])  # UTC
    test.assertIn(reading["source"], {"live", "mock"})


class MonitorTestCase(unittest.TestCase):
    def setUp(self):
        # Start every test with no mock env vars, whatever the developer's shell has
        drop = {"USE_MOCK", "MOCK_SCENARIO", "MONITOR_CITY", "LIVE_CACHE_MINUTES"}
        clean_env = {k: v for k, v in os.environ.items() if k not in drop}
        env_patch = mock.patch.dict(os.environ, clean_env, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        monitor._history.clear()
        monitor._live_cache.clear()


class MockPathTest(MonitorTestCase):
    def test_use_mock_skips_network(self):
        os.environ["USE_MOCK"] = "true"
        with mock.patch.object(monitor.requests, "get", side_effect=AssertionError("network called")):
            reading = monitor.fetch_air_quality("Lahore")
        assert_valid_reading(self, reading)
        self.assertEqual(reading["source"], "mock")

    def test_scenario_param_forces_mock(self):
        with mock.patch.object(monitor.requests, "get", side_effect=AssertionError("network called")):
            reading = monitor.fetch_air_quality("Karachi", scenario="hazardous")
        self.assertEqual(reading["source"], "mock")
        self.assertGreater(reading["pm25"], 225.5)

    def test_every_scenario_matches_its_level(self):
        # Each named scenario must land in the AQI level it's named after, at every step
        for level in ("good", "moderate", "unhealthy_sensitive", "unhealthy", "very_unhealthy", "hazardous"):
            for reading in monitor.mock_readings("Lahore", level, window=20):
                with self.subTest(level=level, pm25=reading["pm25"]):
                    self.assertEqual(analysis.pm25_to_aqi(reading["pm25"])[1], level)

    def test_mock_window_is_oldest_first(self):
        readings = monitor.mock_readings("Lahore")
        self.assertEqual(len(readings), monitor.WINDOW)
        stamps = [r["timestamp"] for r in readings]
        self.assertEqual(stamps, sorted(stamps))
        for r in readings:
            assert_valid_reading(self, r)


class LivePathTest(MonitorTestCase):
    def test_parses_open_meteo_and_converts_to_utc(self):
        with mock.patch.object(monitor.requests, "get", return_value=fake_response(LAHORE_RESPONSE)) as get:
            reading = monitor.fetch_air_quality("lahore")
        self.assertEqual(reading, {
            "location": "Lahore",
            "timestamp": "2026-10-17T06:00:00+00:00",  # 11:00 in Pakistan (UTC+5)
            "pm25": 23.5,
            "pm10": 30.6,
            "source": "live",
        })
        self.assertEqual(get.call_args.kwargs["timeout"], 10)

    def test_missing_pm10_becomes_none(self):
        body = {**LAHORE_RESPONSE, "current": {**LAHORE_RESPONSE["current"], "pm10": None}}
        with mock.patch.object(monitor.requests, "get", return_value=fake_response(body)):
            reading = monitor.fetch_air_quality("Lahore")
        self.assertEqual(reading["source"], "live")
        self.assertIsNone(reading["pm10"])


class FallbackTest(MonitorTestCase):
    def check_falls_back(self, **get_behaviour):
        with mock.patch.object(monitor.requests, "get", **get_behaviour):
            reading = monitor.fetch_air_quality("Lahore")
        assert_valid_reading(self, reading)
        self.assertEqual(reading["source"], "mock")

    def test_timeout(self):
        self.check_falls_back(side_effect=requests.Timeout("too slow"))

    def test_no_network(self):
        self.check_falls_back(side_effect=requests.ConnectionError("offline"))

    def test_http_400(self):
        self.check_falls_back(return_value=fake_response({"error": True, "reason": "bad latitude"}, 400))

    def test_null_pm25(self):
        body = {**LAHORE_RESPONSE, "current": {**LAHORE_RESPONSE["current"], "pm2_5": None}}
        self.check_falls_back(return_value=fake_response(body))

    def test_unknown_city_does_not_crash(self):
        with mock.patch.object(monitor.requests, "get", side_effect=AssertionError("network called")):
            reading = monitor.fetch_air_quality("Atlantis")
        self.assertEqual(reading["source"], "mock")
        self.assertEqual(reading["location"], "Atlantis")


class CacheTest(MonitorTestCase):
    def test_polling_reuses_the_live_reading(self):
        with mock.patch.object(monitor.requests, "get", return_value=fake_response(LAHORE_RESPONSE)) as get:
            first = monitor.fetch_air_quality("Lahore")
            for _ in range(10):  # ten dashboard polls
                monitor.run({})
            again = monitor.fetch_air_quality("Lahore")
        self.assertEqual(get.call_count, 1)
        self.assertEqual(first, again)

    def test_cache_expires(self):
        with mock.patch.object(monitor.requests, "get", return_value=fake_response(LAHORE_RESPONSE)) as get, \
                mock.patch.object(monitor.time, "monotonic", return_value=1000.0) as clock:
            monitor.fetch_air_quality("Lahore")
            clock.return_value = 1000.0 + 9 * 60
            monitor.fetch_air_quality("Lahore")
            self.assertEqual(get.call_count, 1)
            clock.return_value = 1000.0 + 10 * 60
            monitor.fetch_air_quality("Lahore")
            self.assertEqual(get.call_count, 2)

    def test_zero_turns_cache_off(self):
        os.environ["LIVE_CACHE_MINUTES"] = "0"
        with mock.patch.object(monitor.requests, "get", return_value=fake_response(LAHORE_RESPONSE)) as get:
            monitor.fetch_air_quality("Lahore")
            monitor.fetch_air_quality("Lahore")
        self.assertEqual(get.call_count, 2)

    def test_cities_are_cached_separately(self):
        with mock.patch.object(monitor.requests, "get", return_value=fake_response(LAHORE_RESPONSE)) as get:
            monitor.fetch_air_quality("Lahore")
            monitor.fetch_air_quality("Karachi")
        self.assertEqual(get.call_count, 2)

    def test_failures_are_not_cached(self):
        with mock.patch.object(monitor.requests, "get", side_effect=requests.ConnectionError("offline")):
            self.assertEqual(monitor.fetch_air_quality("Lahore")["source"], "mock")
        with mock.patch.object(monitor.requests, "get", return_value=fake_response(LAHORE_RESPONSE)):
            self.assertEqual(monitor.fetch_air_quality("Lahore")["source"], "live")

    def test_cached_reading_cannot_be_changed_by_callers(self):
        with mock.patch.object(monitor.requests, "get", return_value=fake_response(LAHORE_RESPONSE)):
            monitor.fetch_air_quality("Lahore")["pm25"] = -1
            self.assertEqual(monitor.fetch_air_quality("Lahore")["pm25"], 23.5)

    def test_bad_env_value_uses_default(self):
        os.environ["LIVE_CACHE_MINUTES"] = "soon"
        self.assertEqual(monitor._cache_seconds(), monitor.DEFAULT_CACHE_MINUTES * 60)


class GraphNodeTest(MonitorTestCase):
    def test_run_output_feeds_analysis(self):
        os.environ["MOCK_SCENARIO"] = "hazardous"
        result = monitor.run({})
        self.assertEqual(set(result), {"readings"})  # only the key the monitor owns
        self.assertTrue(analysis.run(result)["analysis"]["is_hazardous"])

    def test_run_live_does_not_duplicate_same_hour(self):
        with mock.patch.object(monitor.requests, "get", return_value=fake_response(LAHORE_RESPONSE)):
            monitor.run({})
            readings = monitor.run({})["readings"]
        self.assertEqual(len(readings), 1)

    def test_run_falls_back_when_offline(self):
        with mock.patch.object(monitor.requests, "get", side_effect=requests.ConnectionError("offline")):
            readings = monitor.run({})["readings"]
        self.assertEqual(len(readings), monitor.WINDOW)
        self.assertTrue(all(r["source"] == "mock" for r in readings))


if __name__ == "__main__":
    unittest.main()
