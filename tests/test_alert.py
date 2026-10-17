"""Tests for the alert agent. No network: Telegram calls are faked, the store is a temp file.

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

import requests  # noqa: E402

from agents import advisory, alert, analysis  # noqa: E402
from schemas import Alert  # noqa: E402

MOCK = json.loads((Path(__file__).parent.parent / "data" / "mock_readings.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
COOLDOWN = timedelta(minutes=30)
FAKE_TOKEN = "123456:SECRET-TOKEN"


def state_for(values: list, location: str = "Lahore", source: str = "live") -> dict:
    """Full pipeline state (readings -> analysis -> advisory) for a window of PM2.5 values."""
    start = datetime(2026, 10, 17, tzinfo=timezone.utc)
    state = {"readings": [
        {"location": location, "timestamp": (start + timedelta(hours=i)).isoformat(),
         "pm25": v, "pm10": None, "source": source}
        for i, v in enumerate(values)
    ]}
    state.update(analysis.run(state))
    state.update(advisory.run(state))
    return state


def scenario_windows(name: str, size: int = 6) -> list[list[float]]:
    """Every sliding window the monitor produces while cycling a scenario once."""
    values = MOCK["scenarios"][name]["pm25"]
    n = len(values)
    return [[values[(end - back) % n] for back in range(size - 1, -1, -1)] for end in range(n)]


class AlertTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store_patch = mock.patch.object(alert, "STORE_FILE", Path(tmp.name) / "alerts.json")
        store_patch.start()
        self.addCleanup(store_patch.stop)
        drop = {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ALERT_COOLDOWN_MINUTES", "ALERT_MEMORY_HOURS",
                "USE_MOCK", "MOCK_SCENARIO", "ALERT_SIMULATIONS_TO_TELEGRAM"}
        env_patch = mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k not in drop}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        # Act as if this process already started; startup tests flip it back
        startup_patch = mock.patch.object(alert, "_startup_done", True)
        startup_patch.start()
        self.addCleanup(startup_patch.stop)


class DecisionTest(unittest.TestCase):
    """The pure anti-spam rule."""

    def decide(self, level, memory=None, spike=False, at=NOW):
        return alert.should_alert(level, spike, memory, at, COOLDOWN)

    def test_no_alert_for_good_or_moderate(self):
        for level in ("good", "moderate"):
            self.assertFalse(self.decide(level)[0], level)

    def test_alert_at_threshold(self):
        self.assertTrue(self.decide("unhealthy_sensitive")[0])

    def test_same_level_does_not_repeat_even_after_cooldown(self):
        _, memory = self.decide("unhealthy")
        self.assertFalse(self.decide("unhealthy", memory)[0])
        self.assertFalse(self.decide("unhealthy", memory, at=NOW + timedelta(hours=5))[0])

    def test_level_increase_alerts_immediately(self):
        _, memory = self.decide("unhealthy")
        self.assertTrue(self.decide("very_unhealthy", memory, at=NOW + timedelta(minutes=1))[0])

    def test_flapping_within_cooldown_is_quiet(self):
        _, memory = self.decide("unhealthy")
        _, memory = self.decide("unhealthy_sensitive", memory, at=NOW + timedelta(minutes=5))
        self.assertFalse(self.decide("unhealthy", memory, at=NOW + timedelta(minutes=10))[0])

    def test_rise_after_quiet_recovery_alerts_again(self):
        _, memory = self.decide("unhealthy")
        _, memory = self.decide("moderate", memory, at=NOW + timedelta(minutes=40))
        self.assertTrue(self.decide("unhealthy", memory, at=NOW + timedelta(minutes=45))[0])

    def test_spike_alerts_even_at_moderate_once_per_cooldown(self):
        alerted, memory = self.decide("moderate", spike=True)
        self.assertTrue(alerted)
        self.assertFalse(self.decide("moderate", memory, spike=True, at=NOW + timedelta(minutes=5))[0])
        self.assertTrue(self.decide("moderate", memory, spike=True, at=NOW + timedelta(minutes=31))[0])

    def test_memory_expires_after_max_age(self):
        _, memory = self.decide("hazardous")
        max_age = timedelta(hours=3)
        self.assertFalse(alert.should_alert("hazardous", False, memory, NOW + timedelta(hours=2), COOLDOWN, max_age)[0])
        self.assertTrue(alert.should_alert("hazardous", False, memory, NOW + timedelta(hours=3), COOLDOWN, max_age)[0])

    def test_garbage_memory_is_treated_as_empty(self):
        self.assertTrue(self.decide("unhealthy", {"level": "???", "alerted_at": "yesterday"})[0])


class UrgencyTest(unittest.TestCase):
    def test_mapping(self):
        expected = {"unhealthy_sensitive": "info", "unhealthy": "warning",
                    "very_unhealthy": "critical", "hazardous": "critical"}
        for level, urgency in expected.items():
            self.assertEqual(alert.urgency_for(level), urgency, level)

    def test_unknown_level_is_warning(self):
        self.assertEqual(alert.urgency_for("mystery"), "warning")


class RunTest(AlertTestCase):
    def test_repeated_identical_readings_give_one_alert(self):
        state = state_for([80] * 6)
        results = [alert.run(state)["alerts"] for _ in range(5)]
        self.assertEqual([len(r) for r in results], [1, 0, 0, 0, 0])
        self.assertEqual(len(alert.read_feed()), 1)

    def test_level_increase_gives_a_new_alert(self):
        alert.run(state_for([80] * 6))
        new = alert.run(state_for([150] * 6))["alerts"]
        self.assertEqual((new[0]["level"], new[0]["severity"]), ("very_unhealthy", "critical"))
        self.assertEqual([a["level"] for a in alert.read_feed()], ["very_unhealthy", "unhealthy"])  # newest first

    def test_locations_are_tracked_separately(self):
        alert.run(state_for([80] * 6, "Lahore"))
        self.assertEqual(len(alert.run(state_for([80] * 6, "Karachi"))["alerts"]), 1)

    def test_memory_survives_a_restart(self):
        alert.run(state_for([80] * 6))
        # A "restart" only loses module globals; everything else is in the file
        self.assertEqual(alert.run(state_for([80] * 6))["alerts"], [])

    def test_reset_memory_lets_the_demo_alert_again_and_keeps_the_feed(self):
        alert.run(state_for([80] * 6))
        alert.reset_memory()
        self.assertEqual(len(alert.run(state_for([80] * 6))["alerts"]), 1)
        self.assertEqual(len(alert.read_feed()), 2)

    def test_startup_with_forced_mock_clears_memory(self):
        # The rehearsal: hazardous alert, then the process stops
        alert.run(state_for([300] * 6))
        self.assertEqual(alert.run(state_for([300] * 6))["alerts"], [])
        # Demo: a new process with MOCK_SCENARIO=hazardous must alert again
        for forced in ({"MOCK_SCENARIO": "hazardous"}, {"USE_MOCK": "true"}):
            with self.subTest(env=forced), mock.patch.dict(os.environ, forced), \
                    mock.patch.object(alert, "_startup_done", False):
                self.assertEqual(len(alert.run(state_for([300] * 6))["alerts"]), 1)
                self.assertEqual(alert.run(state_for([300] * 6))["alerts"], [])  # only the first run clears

    def test_startup_in_live_mode_keeps_memory(self):
        alert.run(state_for([300] * 6))
        with mock.patch.object(alert, "_startup_done", False):
            self.assertEqual(alert.run(state_for([300] * 6))["alerts"], [])

    def test_memory_hours_env_var(self):
        os.environ["ALERT_MEMORY_HOURS"] = "6"
        self.assertEqual(alert._memory_max_age(), timedelta(hours=6))
        for bad in ("0", "-1", "soon"):
            os.environ["ALERT_MEMORY_HOURS"] = bad
            self.assertEqual(alert._memory_max_age(), timedelta(hours=alert.DEFAULT_MEMORY_HOURS), bad)

    def test_bad_input_never_raises(self):
        for state in ({}, {"analysis": {"level": "nope"}}, {"analysis": {"level": "hazardous"}, "readings": None}):
            with self.subTest(state=state):
                self.assertIsInstance(alert.run(state)["alerts"], list)

    def test_corrupt_store_is_replaced(self):
        alert.STORE_FILE.write_text("{not json", encoding="utf-8")
        self.assertEqual(len(alert.run(state_for([80] * 6))["alerts"]), 1)

    def test_cooldown_env_var(self):
        os.environ["ALERT_COOLDOWN_MINUTES"] = "0"
        state = state_for([12, 12, 12, 12, 12, 40])  # spike
        self.assertEqual(len(alert.run(state)["alerts"]), 1)
        self.assertEqual(len(alert.run(state)["alerts"]), 1)  # no cooldown -> spike alerts again
        os.environ["ALERT_COOLDOWN_MINUTES"] = "soon"
        self.assertEqual(alert._cooldown(), timedelta(minutes=alert.DEFAULT_COOLDOWN_MINUTES))


class DeliveryTest(AlertTestCase):
    def raise_alert(self) -> Alert:
        return alert.run(state_for([150] * 6))["alerts"][0]

    def test_no_credentials_uses_feed(self):
        with mock.patch.object(alert.requests, "post", side_effect=AssertionError("network called")):
            sent = self.raise_alert()
        self.assertEqual((sent["channel"], sent["status"]), ("feed", "sent"))

    def test_placeholder_credentials_use_feed(self):
        os.environ.update(TELEGRAM_BOT_TOKEN="your_token_here", TELEGRAM_CHAT_ID="your_chat_id_here")
        with mock.patch.object(alert.requests, "post", side_effect=AssertionError("network called")):
            self.assertEqual(self.raise_alert()["channel"], "feed")

    def test_telegram_success(self):
        os.environ.update(TELEGRAM_BOT_TOKEN=FAKE_TOKEN, TELEGRAM_CHAT_ID="42")
        with mock.patch.object(alert.requests, "post", return_value=mock.Mock(ok=True)) as post:
            sent = self.raise_alert()
        self.assertEqual((sent["channel"], sent["status"]), ("telegram", "sent"))
        self.assertEqual(post.call_args.kwargs["json"]["chat_id"], "42")
        self.assertEqual(alert.read_feed()[0], sent)  # the feed always has a copy

    def test_telegram_failure_falls_back_to_feed_and_hides_token(self):
        os.environ.update(TELEGRAM_BOT_TOKEN=FAKE_TOKEN, TELEGRAM_CHAT_ID="42")
        error = requests.ConnectionError(f"Max retries for url /bot{FAKE_TOKEN}/sendMessage")
        with mock.patch.object(alert.requests, "post", side_effect=error), self.assertLogs(alert.log, "WARNING") as logs:
            sent = self.raise_alert()
        self.assertEqual(sent["channel"], "feed")
        self.assertTrue(sent["status"].startswith("failed: telegram"))
        self.assertNotIn(FAKE_TOKEN, sent["status"] + " ".join(logs.output))
        self.assertEqual(alert.read_feed()[0], sent)

    def test_telegram_http_error_falls_back(self):
        os.environ.update(TELEGRAM_BOT_TOKEN=FAKE_TOKEN, TELEGRAM_CHAT_ID="42")
        with mock.patch.object(alert.requests, "post", return_value=mock.Mock(ok=False, status_code=401)):
            self.assertEqual(self.raise_alert()["status"], "failed: telegram: HTTP 401")


class SimulationTest(AlertTestCase):
    def setUp(self):
        super().setUp()
        os.environ.update(TELEGRAM_BOT_TOKEN=FAKE_TOKEN, TELEGRAM_CHAT_ID="42")

    def test_mock_alert_is_prefixed(self):
        with mock.patch.object(alert.requests, "post", return_value=mock.Mock(ok=True)):
            sent = alert.run(state_for([300] * 6, source="mock"))["alerts"][0]
        self.assertTrue(sent["message"].startswith("[SIMULATION] Lahore: AQI"))

    def test_live_alert_is_not_prefixed(self):
        with mock.patch.object(alert.requests, "post", return_value=mock.Mock(ok=True)):
            sent = alert.run(state_for([300] * 6, source="live"))["alerts"][0]
        self.assertFalse(sent["message"].startswith("[SIMULATION]"))

    def test_mock_alert_skips_telegram_by_default(self):
        with mock.patch.object(alert.requests, "post", side_effect=AssertionError("Telegram called")):
            sent = alert.run(state_for([300] * 6, source="mock"))["alerts"][0]
        self.assertEqual((sent["channel"], sent["status"]), ("feed", "sent"))
        self.assertEqual(alert.read_feed()[0], sent)

    def test_mock_alert_goes_to_telegram_when_allowed(self):
        os.environ["ALERT_SIMULATIONS_TO_TELEGRAM"] = "true"
        with mock.patch.object(alert.requests, "post", return_value=mock.Mock(ok=True)) as post:
            sent = alert.run(state_for([300] * 6, source="mock"))["alerts"][0]
        self.assertEqual(sent["channel"], "telegram")
        self.assertTrue(post.call_args.kwargs["json"]["text"].startswith("[CRITICAL] [SIMULATION]"))

    def test_unknown_source_counts_as_simulated(self):
        state = state_for([300] * 6)
        del state["readings"][-1]["source"]
        with mock.patch.object(alert.requests, "post", side_effect=AssertionError("Telegram called")):
            self.assertTrue(alert.run(state)["alerts"][0]["message"].startswith("[SIMULATION]"))


class ContractTest(AlertTestCase):
    def test_alert_matches_schema_and_dashboard_format(self):
        alert.run(state_for([300] * 6))
        feed = json.loads(json.dumps(alert.read_feed()))  # what /api/alerts sends to the browser
        item = feed[0]
        self.assertEqual(set(item), set(Alert.__annotations__))
        self.assertIn(item["severity"], {"info", "warning", "critical"})
        self.assertTrue(item["message"].startswith("Lahore: AQI"))
        self.assertEqual(datetime.fromisoformat(item["created_at"]).utcoffset(), timedelta(0))

    def test_all_mock_scenarios_end_to_end(self):
        # Cycle each scenario once through analysis -> advisory -> alert, as the dashboard would
        expected = {
            "good": [], "moderate": [],
            "unhealthy_sensitive": ["info"], "unhealthy": ["warning"],
            "very_unhealthy": ["critical"], "hazardous": ["critical"],
            # rising: sensitive-groups level, then a spike, then each worse level once
            "spike": ["info", "info", "warning", "critical", "critical"],
        }
        for scenario, severities in expected.items():
            with self.subTest(scenario=scenario):
                alert.reset_memory()
                raised = []
                for values in scenario_windows(scenario):
                    raised += alert.run(state_for(values, location=scenario))["alerts"]
                self.assertEqual([a["severity"] for a in raised], severities)


if __name__ == "__main__":
    unittest.main()
