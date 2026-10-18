"""Tests for the alert agent. No network: Telegram calls are faked, the store is a temp file.

Run from the smogshield folder:  python -m unittest discover tests -v
"""
import http.server
import json
import logging
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Tests must never send real Telegram messages, whatever the developer's shell or .env has
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
    os.environ.pop(_key, None)

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
        # Safety net: a background send that outlives a test's own mock must never hit the network
        post_patch = mock.patch.object(alert.requests, "post", side_effect=AssertionError("unexpected Telegram call"))
        post_patch.start()
        self.addCleanup(post_patch.stop)
        self.addCleanup(alert.flush)  # runs first: let background sends finish before the temp store goes


class DecisionTest(unittest.TestCase):
    """The pure anti-spam rule."""

    def decide(self, level, memory=None, spike=False, at=NOW):
        return alert.should_alert(level, spike, memory, at, COOLDOWN)

    def test_no_alert_for_good_or_moderate(self):
        for level in ("good", "satisfactory"):
            self.assertFalse(self.decide(level)[0], level)

    def test_alert_at_threshold(self):
        self.assertTrue(self.decide("moderate")[0])

    def test_same_level_does_not_repeat_even_after_cooldown(self):
        _, memory = self.decide("poor")
        self.assertFalse(self.decide("poor", memory)[0])
        self.assertFalse(self.decide("poor", memory, at=NOW + timedelta(hours=5))[0])

    def test_level_increase_alerts_immediately(self):
        _, memory = self.decide("poor")
        self.assertTrue(self.decide("very_poor", memory, at=NOW + timedelta(minutes=1))[0])

    def test_flapping_within_cooldown_is_quiet(self):
        _, memory = self.decide("poor")
        _, memory = self.decide("moderate", memory, at=NOW + timedelta(minutes=5))
        self.assertFalse(self.decide("poor", memory, at=NOW + timedelta(minutes=10))[0])

    def test_rise_after_quiet_recovery_alerts_again(self):
        _, memory = self.decide("poor")
        _, memory = self.decide("satisfactory", memory, at=NOW + timedelta(minutes=40))
        self.assertTrue(self.decide("poor", memory, at=NOW + timedelta(minutes=45))[0])

    def test_spike_alerts_even_at_moderate_once_per_cooldown(self):
        alerted, memory = self.decide("satisfactory", spike=True)
        self.assertTrue(alerted)
        self.assertFalse(self.decide("satisfactory", memory, spike=True, at=NOW + timedelta(minutes=5))[0])
        self.assertTrue(self.decide("satisfactory", memory, spike=True, at=NOW + timedelta(minutes=31))[0])

    def test_memory_expires_after_max_age(self):
        _, memory = self.decide("severe")
        max_age = timedelta(hours=3)
        self.assertFalse(alert.should_alert("severe", False, memory, NOW + timedelta(hours=2), COOLDOWN, max_age)[0])
        self.assertTrue(alert.should_alert("severe", False, memory, NOW + timedelta(hours=3), COOLDOWN, max_age)[0])

    def test_garbage_memory_is_treated_as_empty(self):
        self.assertTrue(self.decide("poor", {"level": "???", "alerted_at": "yesterday"})[0])


class UrgencyTest(unittest.TestCase):
    def test_mapping(self):
        expected = {"moderate": "info", "poor": "warning",
                    "very_poor": "critical", "severe": "critical"}
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
        self.assertEqual((new[0]["level"], new[0]["severity"]), ("very_poor", "critical"))
        self.assertEqual([a["level"] for a in alert.read_feed()], ["very_poor", "poor"])  # newest first

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
        # The rehearsal: severe alert, then the process stops
        alert.run(state_for([300] * 6))
        self.assertEqual(alert.run(state_for([300] * 6))["alerts"], [])
        # Demo: a new process with MOCK_SCENARIO=severe must alert again
        for forced in ({"MOCK_SCENARIO": "severe"}, {"USE_MOCK": "true"}):
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

    def test_unknown_level_never_alerts(self):
        state = {"readings": []}
        state.update(analysis.run(state))
        state.update(advisory.run(state))
        self.assertEqual(state["analysis"]["level"], "unknown")
        self.assertEqual(alert.run(state)["alerts"], [])
        self.assertEqual(alert.read_feed(), [])

    def test_bad_input_never_raises(self):
        for state in ({}, {"analysis": {"level": "nope"}}, {"analysis": {"level": "severe"}, "readings": None}):
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
        """Raises one alert, waits for any background send, returns the final feed entry."""
        alert.run(state_for([150] * 6))
        alert.flush()
        return alert.read_feed()[0]

    def test_telegram_never_blocks_the_pipeline(self):
        os.environ.update(TELEGRAM_BOT_TOKEN=FAKE_TOKEN, TELEGRAM_CHAT_ID="42")

        def slow_post(*args, **kwargs):
            time.sleep(1.0)
            return mock.Mock(ok=True)

        with mock.patch.object(alert.requests, "post", side_effect=slow_post) as post:
            started = time.monotonic()
            returned = alert.run(state_for([150] * 6))["alerts"][0]
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 0.5)
            self.assertEqual((returned["channel"], returned["status"]), ("telegram", "queued"))
            self.assertEqual(alert.read_feed()[0]["status"], "queued")  # in the feed right away
            alert.flush()
        self.assertEqual(alert.read_feed()[0]["status"], "sent")
        self.assertEqual(post.call_args.kwargs["timeout"], 3)

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
        self.assertTrue(any("delivery failed" in line for line in logs.output))
        self.assertEqual(len(alert.read_feed()), 1)  # updated in place, not duplicated

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
            alert.flush()
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
            alert.flush()
        self.assertEqual(sent["channel"], "telegram")
        self.assertTrue(post.call_args.kwargs["json"]["text"].startswith("[CRITICAL] [SIMULATION]"))

    def test_unknown_source_counts_as_simulated(self):
        state = state_for([300] * 6)
        del state["readings"][-1]["source"]
        with mock.patch.object(alert.requests, "post", side_effect=AssertionError("Telegram called")):
            self.assertTrue(alert.run(state)["alerts"][0]["message"].startswith("[SIMULATION]"))


class _NotFound(http.server.BaseHTTPRequestHandler):
    """Tiny local server: answers 404 to everything, silently."""
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))  # read the body, or Windows aborts
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


class TokenLoggingTest(AlertTestCase):
    def setUp(self):
        super().setUp()
        self.server = http.server.HTTPServer(("127.0.0.1", 0), _NotFound)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}/bot{FAKE_TOKEN}/sendMessage"

    def captured_logs(self) -> str:
        """Everything logged at any level while a real request with the token in its URL is made."""
        urllib3_child = logging.getLogger("urllib3.connectionpool")
        old_level = urllib3_child.level
        urllib3_child.setLevel(logging.DEBUG)  # as if someone turned on debug logging for urllib3
        try:
            with self.assertLogs(level=logging.DEBUG) as logs:  # root logger, DEBUG and up
                logging.getLogger("test").debug("marker")  # assertLogs needs at least one record
                requests.Session().post(self.url, json={}, timeout=3)
                logging.getLogger("urllib3.connectionpool").debug("direct %s", self.url)
        finally:
            urllib3_child.setLevel(old_level)
        return "\n".join(logs.output)

    def test_token_never_reaches_logs(self):
        self.assertNotIn(FAKE_TOKEN, self.captured_logs())

    def test_control_without_silencing_the_token_would_leak(self):
        # Proves the test above can catch a leak: undo the silencing and the token shows up
        urllib3_log = logging.getLogger("urllib3")
        with mock.patch.object(urllib3_log, "level", logging.NOTSET), mock.patch.object(urllib3_log, "propagate", True):
            self.assertIn(FAKE_TOKEN, self.captured_logs())

    def test_telegram_failure_log_hides_token(self):
        os.environ.update(TELEGRAM_BOT_TOKEN=FAKE_TOKEN, TELEGRAM_CHAT_ID="42")
        error = requests.ConnectionError(f"failed for {self.url}")
        with mock.patch.object(alert.requests, "post", side_effect=error), self.assertLogs(level=logging.DEBUG) as logs:
            alert.run(state_for([150] * 6))
            alert.flush()
        self.assertTrue(any("delivery failed" in line for line in logs.output))
        self.assertNotIn(FAKE_TOKEN, "\n".join(logs.output))


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
            "good": [], "satisfactory": [],
            "moderate": ["info"], "poor": ["warning"],
            "very_poor": ["critical"], "severe": ["critical"],
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


# ---------- predictive (forecast) alerts ----------

from agents import forecast as forecast_agent  # noqa: E402


def make_forecast(values: list[float], source: str = "live") -> dict:
    """A forecast whose hour N (from the current hour) has PM2.5 values[N]."""
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    points = [{"time": (start + timedelta(hours=h)).isoformat(), "pm25": float(v)} for h, v in enumerate(values)]
    return forecast_agent._forecast_from_series("Lahore", {"offset": 5 * 3600, "points": points}, source,
                                                datetime.now(timezone.utc))


def with_forecast(values_now: list, forecast_values: list, source: str = "live") -> dict:
    state = state_for(values_now, source=source)
    state["forecast"] = make_forecast(forecast_values, source=source)
    return state


GETS_UNHEALTHY = [30, 40, 60, 70, 70, 70] + [30] * 18       # satisfactory now, Unhealthy from hour 2


class ForecastDecisionTest(unittest.TestCase):
    """The pure rule: current < Unhealthy and forecast peak >= Unhealthy within 6 hours."""

    def decide(self, current, peak, memory=None, current_memory=None, at=NOW):
        return alert.should_forecast_alert(current, peak, memory, current_memory, at, COOLDOWN, timedelta(hours=3))

    def test_fires_only_when_below_unhealthy_now_and_unhealthy_ahead(self):
        cases = {
            ("satisfactory", "poor"): True,
            ("moderate", "severe"): True,
            ("good", "very_poor"): True,
            ("satisfactory", "moderate"): False,   # forecast not bad enough
            ("poor", "very_poor"): False,       # already poor now: the current alert covers it
            ("severe", "severe"): False,
            ("satisfactory", None): False,                    # no forecast
            ("unknown", "severe"): False,
        }
        for (current, peak), expected in cases.items():
            with self.subTest(current=current, peak=peak):
                self.assertEqual(self.decide(current, peak)[0], expected)

    def test_same_forecast_does_not_repeat(self):
        _, memory = self.decide("satisfactory", "poor")
        self.assertFalse(self.decide("satisfactory", "poor", memory, at=NOW + timedelta(minutes=5))[0])
        self.assertFalse(self.decide("satisfactory", "poor", memory, at=NOW + timedelta(hours=2))[0])

    def test_worse_forecast_alerts_again(self):
        _, memory = self.decide("satisfactory", "poor")
        self.assertTrue(self.decide("satisfactory", "very_poor", memory, at=NOW + timedelta(minutes=5))[0])

    def test_rearms_after_the_threat_clears_for_a_cooldown(self):
        _, memory = self.decide("satisfactory", "poor")
        _, memory = self.decide("satisfactory", "satisfactory", memory, at=NOW + timedelta(minutes=10))   # too soon to forget
        self.assertFalse(self.decide("satisfactory", "poor", memory, at=NOW + timedelta(minutes=15))[0])
        _, memory = self.decide("satisfactory", "satisfactory", memory, at=NOW + timedelta(minutes=40))   # quiet for a cooldown
        self.assertTrue(self.decide("satisfactory", "poor", memory, at=NOW + timedelta(minutes=45))[0])

    def test_memory_expires(self):
        _, memory = self.decide("satisfactory", "poor")
        self.assertTrue(self.decide("satisfactory", "poor", memory, at=NOW + timedelta(hours=3))[0])

    def test_no_duplicate_of_a_current_alert_at_that_level(self):
        current_memory = {"level": "poor", "alerted_at": NOW.isoformat()}
        self.assertFalse(self.decide("moderate", "poor", current_memory=current_memory)[0])
        self.assertTrue(self.decide("moderate", "very_poor", current_memory=current_memory)[0])
        stale = {"level": "poor", "alerted_at": (NOW - timedelta(hours=4)).isoformat()}   # expired memory
        self.assertTrue(self.decide("moderate", "poor", current_memory=stale)[0])


class ForecastAlertRunTest(AlertTestCase):
    def test_predictive_alert(self):
        result = alert.run(with_forecast([30] * 6, GETS_UNHEALTHY))["alerts"]
        self.assertEqual(len(result), 1)
        predicted = result[0]
        self.assertEqual((predicted["kind"], predicted["severity"], predicted["level"]), ("forecast", "warning", "poor"))
        self.assertTrue(predicted["message"].startswith("[FORECAST] Lahore: forecast to reach Poor (AQI "))
        self.assertIn("within 6 hours", predicted["message"])
        self.assertEqual(set(predicted), set(Alert.__annotations__))

    def test_never_critical_even_for_hazardous_forecasts(self):
        predicted = alert.run(with_forecast([30] * 6, [30, 300, 400] + [30] * 21))["alerts"][0]
        self.assertEqual((predicted["severity"], predicted["level"]), ("warning", "severe"))

    def test_fires_once_for_repeated_polls(self):
        counts = [len(alert.run(with_forecast([30] * 6, GETS_UNHEALTHY))["alerts"]) for _ in range(4)]
        self.assertEqual(counts, [1, 0, 0, 0])

    def test_no_predictive_alert_when_already_unhealthy(self):
        result = alert.run(with_forecast([80] * 6, [80, 150, 150] + [80] * 21))["alerts"]
        self.assertEqual([a["kind"] for a in result], ["current"])      # the current alert only

    def test_no_predictive_alert_without_a_forecast_threat(self):
        for forecast_values in ([30] * 24, [30, 40, 45, 50, 50, 50] + [80] * 18):   # USG at most, or after 6 h
            with self.subTest(values=forecast_values[:7]):
                alert.reset_memory()
                self.assertEqual(alert.run(with_forecast([30] * 6, forecast_values))["alerts"], [])

    def test_current_and_forecast_alerts_together_in_one_run(self):
        result = alert.run(with_forecast([45] * 6, [45, 60, 70] + [45] * 21))["alerts"]   # USG now, Unhealthy soon
        self.assertEqual([(a["kind"], a["severity"]) for a in result], [("current", "info"), ("forecast", "warning")])

    def test_simulated_forecast_alert_is_labelled_and_kept_off_telegram(self):
        os.environ.update(TELEGRAM_BOT_TOKEN=FAKE_TOKEN, TELEGRAM_CHAT_ID="42")
        with mock.patch.object(alert.requests, "post", side_effect=AssertionError("Telegram called")):
            predicted = alert.run(with_forecast([30] * 6, GETS_UNHEALTHY, source="mock"))["alerts"][0]
        self.assertTrue(predicted["message"].startswith("[SIMULATION] [FORECAST] "))
        self.assertEqual((predicted["channel"], predicted["status"]), ("feed", "sent"))

    def test_live_forecast_alert_goes_to_telegram(self):
        os.environ.update(TELEGRAM_BOT_TOKEN=FAKE_TOKEN, TELEGRAM_CHAT_ID="42")
        with mock.patch.object(alert.requests, "post", return_value=mock.Mock(ok=True)) as post:
            alert.run(with_forecast([30] * 6, GETS_UNHEALTHY))
            alert.flush()
        self.assertTrue(post.call_args.kwargs["json"]["text"].startswith("[WARNING] [FORECAST] "))
        self.assertEqual(alert.read_feed()[0]["channel"], "telegram")

    def test_bad_forecasts_never_raise(self):
        state = state_for([30] * 6)
        for bad in (None, "nonsense", {}, {"next_6h": "x"}, {"next_6h": {"peak_level": "poor"}}):
            with self.subTest(forecast=bad):
                state["forecast"] = bad
                self.assertIsInstance(alert.run(state)["alerts"], list)

    def test_unhealthy_sensitive_scenario_predicts_end_to_end(self):
        readings = state_for(MOCK["scenarios"]["moderate"]["pm25"][:6], source="mock")
        readings["forecast"] = forecast_agent.mock_forecast("Lahore", readings["readings"][-1]["pm25"],
                                                            scenario="moderate")
        kinds = [a["kind"] for a in alert.run(readings)["alerts"]]
        self.assertIn("forecast", kinds)


class KindCompatibilityTest(AlertTestCase):
    def test_old_stored_alerts_read_as_current_without_rewriting_the_file(self):
        old = {"severity": "critical", "message": "Lahore: AQI 300 (Hazardous).", "created_at": NOW.isoformat(),
               "location": "Lahore", "level": "severe", "channel": "feed", "status": "sent"}
        alert.STORE_FILE.write_text(json.dumps({"memory": {}, "feed": [old]}), encoding="utf-8")
        before = alert.STORE_FILE.read_bytes()
        feed = alert.read_feed()
        self.assertEqual(feed[0]["kind"], "current")
        self.assertEqual(set(feed[0]), set(Alert.__annotations__))
        self.assertEqual(alert.STORE_FILE.read_bytes(), before)              # nothing written back

    def test_new_current_alerts_have_kind_current(self):
        self.assertEqual(alert.run(state_for([300] * 6))["alerts"][0]["kind"], "current")


if __name__ == "__main__":
    unittest.main()
