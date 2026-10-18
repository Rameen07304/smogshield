"""Tests for the analysis agent. Pure functions, no network.

Run from the smogshield folder:  python -m unittest discover tests -v
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Tests must never send real Telegram messages, whatever the developer's shell or .env has
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
    os.environ.pop(_key, None)

from agents import advisory, alert, analysis  # noqa: E402
from schemas import Analysis  # noqa: E402

MOCK = json.loads((Path(__file__).parent.parent / "data" / "mock_readings.json").read_text(encoding="utf-8"))
START = datetime(2026, 10, 17, tzinfo=timezone.utc)


def window(values: list, hours_apart: float = 1.0) -> list[dict]:
    """Readings with the given PM2.5 values, oldest first, evenly spaced in time."""
    return [
        {
            "location": "Lahore",
            "timestamp": (START + timedelta(hours=i * hours_apart)).isoformat(),
            "pm25": v,
            "pm10": None,
            "source": "mock",
        }
        for i, v in enumerate(values)
    ]


def scenario_windows(name: str, size: int = 6) -> list[list[float]]:
    """Every sliding window the monitor can produce while cycling a mock scenario."""
    values = MOCK["scenarios"][name]["pm25"]
    n = len(values)
    return [[values[(end - back) % n] for back in range(size - 1, -1, -1)] for end in range(n)]


class AqiTest(unittest.TestCase):
    def test_every_band_boundary(self):
        # (PM2.5, expected AQI, expected level) from the EPA 2024 table
        cases = [
            (0.0, 0, "good"), (9.0, 50, "good"),
            (9.1, 51, "satisfactory"), (35.4, 100, "satisfactory"),
            (35.5, 101, "moderate"), (55.4, 150, "moderate"),
            (55.5, 151, "poor"), (125.4, 200, "poor"),
            (125.5, 201, "very_poor"), (225.4, 300, "very_poor"),
            (225.5, 301, "severe"), (325.4, 500, "severe"),
        ]
        for pm25, aqi, level in cases:
            with self.subTest(pm25=pm25):
                self.assertEqual(analysis.pm25_to_aqi(pm25), (aqi, level))

    def test_above_top_band_caps_at_500(self):
        for pm25 in (325.5, 500, 999, 5000):
            with self.subTest(pm25=pm25):
                self.assertEqual(analysis.pm25_to_aqi(pm25), (500, "severe"))

    def test_interpolates_inside_a_band(self):
        self.assertEqual(analysis.pm25_to_aqi(12.0), (56, "satisfactory"))  # EPA calculator: 56

    def test_truncates_to_one_decimal(self):
        self.assertEqual(analysis.pm25_to_aqi(9.05), (50, "good"))  # 9.05 -> 9.0, not 9.1

    def test_negative_is_treated_as_zero(self):
        self.assertEqual(analysis.pm25_to_aqi(-5), (0, "good"))


class ScenarioTest(unittest.TestCase):
    LEVELS = ["good", "satisfactory", "moderate", "poor", "very_poor", "severe"]

    def test_each_level_scenario_lands_in_its_own_level(self):
        for level in self.LEVELS:
            for values in scenario_windows(level):
                with self.subTest(scenario=level, latest=values[-1]):
                    result = analysis.assess(window(values))
                    self.assertEqual(result["level"], level)
                    self.assertEqual(result["is_hazardous"], level in analysis.HAZARDOUS_LEVELS)
                    self.assertFalse(result["is_spike"])  # steady scenarios never spike

    def test_spike_scenario_spikes_then_peaks_hazardous(self):
        results = [analysis.assess(window(v)) for v in scenario_windows("spike")]
        self.assertTrue(any(r["is_spike"] for r in results))
        self.assertIn("severe", {r["level"] for r in results})
        self.assertIn("rising", {r["trend"] for r in results})
        self.assertIn("falling", {r["trend"] for r in results})


class TrendTest(unittest.TestCase):
    def test_rising(self):
        result = analysis.assess(window([20, 25, 30, 35, 40, 45]))
        self.assertEqual(result["trend"], "rising")
        self.assertEqual(result["trend_per_hour"], 5.0)

    def test_falling(self):
        result = analysis.assess(window([45, 40, 35, 30, 25, 20]))
        self.assertEqual(result["trend"], "falling")
        self.assertEqual(result["trend_per_hour"], -5.0)

    def test_stable_with_noise(self):
        self.assertEqual(analysis.assess(window([50, 51, 49, 50, 51, 50]))["trend"], "stable")

    def test_small_change_in_clean_air_is_stable(self):
        self.assertEqual(analysis.assess(window([4.0, 4.2, 4.4, 4.6, 4.8, 5.0]))["trend"], "stable")

    def test_rate_uses_real_time_gaps(self):
        # +10 µg/m³ every 2 hours is 5 per hour
        self.assertEqual(analysis.trend_per_hour(window([20, 30, 40], hours_apart=2)), 5.0)

    def test_one_reading(self):
        result = analysis.assess(window([80]))
        self.assertEqual((result["trend"], result["trend_per_hour"], result["is_spike"]), ("stable", 0.0, False))
        self.assertIn("only 1 reading", result["reason"])

    def test_same_timestamps_do_not_divide_by_zero(self):
        self.assertEqual(analysis.trend_per_hour(window([20, 40], hours_apart=0)), 0.0)

    def test_bad_timestamps_assume_hourly(self):
        readings = window([20, 25, 30])
        readings[1]["timestamp"] = "not a time"
        self.assertEqual(analysis.trend_per_hour(readings), 5.0)


class SpikeTest(unittest.TestCase):
    def test_jump_while_still_satisfactory(self):
        result = analysis.assess(window([12, 13, 12, 14, 13, 32]))
        self.assertEqual(result["level"], "satisfactory")
        self.assertTrue(result["is_spike"])
        self.assertIn("spike", result["reason"])

    def test_steady_high_is_not_a_spike(self):
        self.assertFalse(analysis.is_spike([300, 310, 305, 315, 320, 330]))

    def test_small_jump_in_clean_air_is_not_a_spike(self):
        self.assertFalse(analysis.is_spike([4, 4, 4, 4, 4, 9]))  # +125% but only +5 µg/m³

    def test_gradual_rise_is_not_a_spike(self):
        self.assertFalse(analysis.is_spike([40, 44, 48, 52, 56, 60]))

    def test_too_short(self):
        self.assertFalse(analysis.is_spike([]))
        self.assertFalse(analysis.is_spike([200]))


class BadInputTest(unittest.TestCase):
    def test_missing_or_empty_readings(self):
        for state in ({}, {"readings": []}, {"readings": None}):
            with self.subTest(state=state):
                result = analysis.run(state)["analysis"]
                self.assertEqual(set(result), set(Analysis.__annotations__))
                self.assertIn("No valid readings", result["reason"])
                self.assertEqual((result["level"], result["aqi"]), ("unknown", None))  # never "good"
                self.assertFalse(result["is_hazardous"])

    def test_only_invalid_readings_is_unknown(self):
        result = analysis.run({"readings": [{"pm25": None}, {"pm25": "abc"}, {"pm25": -1}]})["analysis"]
        self.assertEqual(result["level"], "unknown")

    def test_invalid_readings_are_skipped(self):
        readings = window([30, 40, 50])
        readings.insert(1, {"pm25": None})
        readings.insert(2, {"pm25": float("nan"), "timestamp": "2026-10-17T00:30:00+00:00"})
        readings.insert(3, {"pm25": -3, "timestamp": "2026-10-17T00:40:00+00:00"})
        readings.append({"timestamp": "2026-10-17T05:00:00+00:00"})  # no pm25 at all
        result = analysis.run({"readings": readings})["analysis"]
        self.assertEqual(result["aqi"], analysis.pm25_to_aqi(50)[0])

    def test_numeric_strings_are_accepted(self):
        self.assertEqual(analysis.run({"readings": window(["35.5"])})["analysis"]["aqi"], 101)


class OutputContractTest(unittest.TestCase):
    def setUp(self):
        # The alert agent remembers past alerts in a file; use a fresh temp one per test
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store_patch = mock.patch.object(alert, "STORE_FILE", Path(tmp.name) / "alerts.json")
        store_patch.start()
        self.addCleanup(store_patch.stop)

    def test_matches_schema(self):
        result = analysis.run({"readings": window([22, 28, 35, 41, 55, 68])})
        self.assertEqual(set(result), {"analysis"})  # only the key analysis owns
        a = result["analysis"]
        self.assertEqual(set(a), set(Analysis.__annotations__))
        self.assertIsInstance(a["aqi"], int)
        self.assertIn(a["level"], analysis.LEVEL_LABELS)
        self.assertIn(a["trend"], {"rising", "falling", "stable"})
        self.assertIsInstance(a["trend_per_hour"], float)
        self.assertIsInstance(a["is_hazardous"], bool)
        self.assertIsInstance(a["is_spike"], bool)
        self.assertTrue(a["reason"])

    def test_feeds_advisory_and_alert(self):
        for level in ScenarioTest.LEVELS + ["spike"]:
            with self.subTest(scenario=level):
                state = {"readings": window(MOCK["scenarios"][level]["pm25"][:6])}
                state.update(analysis.run(state))
                state.update(advisory.run(state))
                state.update(alert.run(state))
                self.assertTrue(state["advisory"]["headline"])
                self.assertIsInstance(state["alerts"], list)


if __name__ == "__main__":
    unittest.main()
