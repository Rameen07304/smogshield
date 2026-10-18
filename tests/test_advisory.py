"""Tests for the advisory agent. Pure functions, no network.

Run from the smogshield folder:  python -m unittest discover tests -v
"""
import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Tests must never send real Telegram messages, whatever the developer's shell or .env has
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
    os.environ.pop(_key, None)

from agents import advisory, alert, analysis, monitor  # noqa: E402
from schemas import Advisory, Audience, UrduAdvisory  # noqa: E402

LEVELS = ["good", "satisfactory", "moderate", "poor", "very_poor", "severe"]
AUDIENCES = list(Audience.__args__)


def make_analysis(level: str, trend: str = "stable", is_spike: bool = False) -> dict:
    """A minimal Analysis-shaped dict; advisory only reads level, trend and is_spike."""
    return {"aqi": 100, "level": level, "trend": trend, "trend_per_hour": 0.0,
            "is_hazardous": level in analysis.HAZARDOUS_LEVELS, "is_spike": is_spike, "reason": "test"}


def all_text(result: dict) -> str:
    """Every English line of advice, lower-cased, for keyword checks."""
    lines = [result["headline"], *result["actions"]]
    for actions in result["audiences"].values():
        lines += actions
    return " ".join(lines).lower()


class LevelTest(unittest.TestCase):
    def test_every_level_has_advice_for_every_audience(self):
        for level in LEVELS:
            result = advisory.build_advisory(make_analysis(level))
            for audience in AUDIENCES:
                with self.subTest(level=level, audience=audience):
                    self.assertTrue(result["audiences"][audience])
                    self.assertTrue(all(line.strip() for line in result["audiences"][audience]))

    def test_every_level_has_urdu(self):
        for level in LEVELS:
            with self.subTest(level=level):
                urdu = advisory.build_advisory(make_analysis(level))["urdu"]
                self.assertTrue(urdu["headline"])
                self.assertIn(advisory.DISCLAIMER_UR, urdu["actions"])

    def test_disclaimer_always_present(self):
        for level in LEVELS:
            self.assertIn("not medical advice", advisory.build_advisory(make_analysis(level))["disclaimer"])
            self.assertIn("National Clean Air Policy", advisory.build_advisory(make_analysis(level))["disclaimer"])


class SeverityTest(unittest.TestCase):
    def test_outdoor_workers_get_level_appropriate_advice(self):
        good = advisory.build_advisory(make_analysis("good"))["audiences"]["outdoor_workers"]
        severe = advisory.build_advisory(make_analysis("severe"))["audiences"]["outdoor_workers"]
        self.assertNotIn("mask", " ".join(good).lower())
        self.assertIn("stop", " ".join(severe).lower())
        self.assertIn("n95", " ".join(severe).lower())

    def test_headlines_use_project_level_names(self):
        expected = {
            "good": "Good air quality.",
            "satisfactory": "Satisfactory air quality.",
            "moderate": "Moderate air quality.",
            "poor": "Poor air quality. Everyone may feel effects.",
            "very_poor": "Very poor air quality. Health alert.",
            "severe": "Severe air quality. Emergency conditions.",
        }
        for level, headline in expected.items():
            with self.subTest(level=level):
                self.assertEqual(advisory.build_advisory(make_analysis(level))["headline"], headline)

    def test_masks_only_from_unhealthy_up(self):
        for level in LEVELS:
            with self.subTest(level=level):
                says_mask = "mask" in all_text(advisory.build_advisory(make_analysis(level)))
                self.assertEqual(says_mask, level in {"moderate", "poor", "very_poor", "severe"})

    def test_hazardous_says_stay_indoors_and_good_does_not(self):
        severe = advisory.build_advisory(make_analysis("severe"))
        good = advisory.build_advisory(make_analysis("good"))
        self.assertIn("stay indoors", " ".join(severe["audiences"]["general"]).lower())
        for word in ("indoors", "mask", "avoid", "reduce"):
            self.assertNotIn(word, all_text(good))

    def test_sensitive_groups_get_warned_before_the_public(self):
        usg = advisory.build_advisory(make_analysis("moderate"))
        self.assertIn("reduce", " ".join(usg["audiences"]["respiratory_heart"]).lower())
        self.assertIn("most people can continue", " ".join(usg["audiences"]["general"]).lower())

    def test_general_advice_grows_with_severity(self):
        # A rough monotonic check: more severe levels never give fewer public actions
        counts = [len(advisory.GUIDANCE[level]["general"]) for level in LEVELS]
        self.assertEqual(counts, sorted(counts))


class TimeContextTest(unittest.TestCase):
    def test_spike_note_comes_first(self):
        result = advisory.build_advisory(make_analysis("satisfactory", trend="rising", is_spike=True))
        self.assertEqual(result["time_note"], advisory.SPIKE_NOTE[0])
        self.assertEqual(result["actions"][0], advisory.SPIKE_NOTE[0])
        self.assertEqual(result["urdu"]["actions"][0], advisory.SPIKE_NOTE[1])

    def test_rising(self):
        result = advisory.build_advisory(make_analysis("poor", trend="rising"))
        self.assertIn("worsening", result["time_note"])
        self.assertEqual(result["actions"][0], result["time_note"])

    def test_falling(self):
        self.assertIn("improving", advisory.build_advisory(make_analysis("poor", trend="falling"))["time_note"])

    def test_stable_has_no_note(self):
        result = advisory.build_advisory(make_analysis("poor"))
        self.assertEqual(result["time_note"], "")
        self.assertEqual(result["actions"], result["audiences"]["general"])

    def test_rising_in_good_or_moderate_air_is_gentle(self):
        for level in ("good", "satisfactory"):
            with self.subTest(level=level):
                result = advisory.build_advisory(make_analysis(level, trend="rising"))
                self.assertEqual(result["time_note"], advisory.GENTLE_RISING_NOTE[0])
                self.assertEqual(result["urdu"]["actions"][0], advisory.GENTLE_RISING_NOTE[1])
                self.assertNotIn("postpone", " ".join(result["actions"]).lower())  # no contradiction

    def test_rising_from_sensitive_groups_up_says_postpone(self):
        for level in ("moderate", "poor", "very_poor", "severe"):
            with self.subTest(level=level):
                self.assertEqual(advisory.build_advisory(make_analysis(level, trend="rising"))["time_note"],
                                 advisory.RISING_NOTE[0])

    def test_good_air_has_no_note_unless_rising(self):
        for trend in ("stable", "falling"):
            self.assertEqual(advisory.build_advisory(make_analysis("good", trend=trend))["time_note"], "")

    def test_time_note_never_changes_severity(self):
        for level in LEVELS:
            plain = advisory.build_advisory(make_analysis(level))
            noted = advisory.build_advisory(make_analysis(level, trend="rising", is_spike=True))
            with self.subTest(level=level):
                self.assertEqual(plain["headline"], noted["headline"])
                self.assertEqual(plain["audiences"], noted["audiences"])


class BadInputTest(unittest.TestCase):
    def test_missing_or_unknown_level_gives_cautious_advice(self):
        cautious = advisory.GUIDANCE[advisory.FALLBACK_LEVEL]
        for bad in (None, {}, {"level": "apocalyptic"}, {"level": None}, "not a dict"):
            with self.subTest(analysis=bad):
                result = advisory.build_advisory(bad)
                self.assertEqual(result["headline"], advisory.FALLBACK_HEADLINE)
                self.assertEqual(result["audiences"]["general"], cautious["general"])
                self.assertIn("mask", all_text(result))

    def test_unknown_level_says_data_unavailable_not_good(self):
        result = advisory.build_advisory({**make_analysis("good"), "level": "unknown", "aqi": None})
        self.assertIn("unavailable", result["headline"].lower())
        self.assertNotIn("good", result["headline"].lower())
        self.assertEqual(result["time_note"], advisory.UNAVAILABLE_NOTE[0])
        self.assertEqual(result["actions"][0], advisory.UNAVAILABLE_NOTE[0])
        self.assertIn("mask", all_text(result))  # cautious advice
        self.assertEqual(result["urdu"]["headline"], advisory.FALLBACK_HEADLINE_UR)

    def test_no_readings_end_to_end_is_cautious(self):
        state = analysis.run({"readings": []})
        result = advisory.run(state)["advisory"]
        self.assertEqual(result["headline"], advisory.FALLBACK_HEADLINE)

    def test_unknown_level_ignores_trend_and_spike(self):
        result = advisory.build_advisory({"level": "unknown", "trend": "rising", "is_spike": True})
        self.assertEqual(result["time_note"], advisory.UNAVAILABLE_NOTE[0])

    def test_run_without_analysis(self):
        self.assertEqual(advisory.run({})["advisory"]["headline"], advisory.FALLBACK_HEADLINE)

    def test_output_does_not_share_the_template_lists(self):
        result = advisory.build_advisory(make_analysis("severe"))
        result["audiences"]["general"].append("mutated")
        self.assertNotIn("mutated", advisory.GUIDANCE["severe"]["general"])


class GroqAdvisoryTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "LLM_ADVISORY_ENABLED": "true",
            "GROQ_API_KEY": "test-key",
            "GROQ_MODEL": "test-model",
        }, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        advisory._llm_cache.clear()
        self.addCleanup(advisory._llm_cache.clear)

    def _response(self, payload):
        audiences = {audience: [f"LLM advice for {audience}"] for audience in AUDIENCES}
        body = {"headline": "LLM headline", "actions": ["LLM action"], "audiences": audiences}
        return mock.Mock(
            json=mock.Mock(return_value={"choices": [{"message": {"content": json.dumps(body)}}]}),
            raise_for_status=mock.Mock(),
        )

    def test_valid_response_replaces_templates_and_preserves_time_note(self):
        with mock.patch.object(advisory.requests, "post", return_value=self._response(None)) as post:
            result = advisory.build_advisory(make_analysis("poor", trend="rising"))
        self.assertEqual(result["headline"], "LLM headline")
        self.assertEqual(result["audiences"]["outdoor_workers"], ["LLM advice for outdoor_workers"])
        self.assertEqual(result["actions"][0], advisory.RISING_NOTE[0])
        post.assert_called_once()

    def test_api_failure_uses_rule_based_advice(self):
        with mock.patch.object(advisory.requests, "post", side_effect=advisory.requests.RequestException("offline")):
            result = advisory.build_advisory(make_analysis("severe"))
        self.assertEqual(result["headline"], "Severe air quality. Emergency conditions.")
        self.assertIn("stop", " ".join(result["audiences"]["outdoor_workers"]).lower())

    def test_repeated_polls_reuse_one_groq_answer(self):
        with mock.patch.object(advisory.requests, "post", return_value=self._response(None)) as post:
            for _ in range(5):  # the dashboard polls every 5 s
                result = advisory.build_advisory(make_analysis("poor", trend="rising"))
            result["audiences"]["general"].append("mutated")
            again = advisory.build_advisory(make_analysis("poor", trend="rising"))
        post.assert_called_once()
        self.assertNotIn("mutated", again["audiences"]["general"])

    def test_failure_is_not_retried_on_every_poll(self):
        with mock.patch.object(advisory.requests, "post", side_effect=advisory.requests.RequestException("offline")) as post:
            for _ in range(3):
                advisory.build_advisory(make_analysis("severe"))
        post.assert_called_once()


class ContractTest(unittest.TestCase):
    def setUp(self):
        # The alert agent remembers past alerts in a file; use a fresh temp one per test
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store_patch = mock.patch.object(alert, "STORE_FILE", Path(tmp.name) / "alerts.json")
        store_patch.start()
        self.addCleanup(store_patch.stop)

    def test_matches_schema(self):
        result = advisory.run({"analysis": make_analysis("poor", trend="rising")})
        self.assertEqual(set(result), {"advisory"})  # only the key advisory owns
        adv = result["advisory"]
        self.assertEqual(set(adv), set(Advisory.__annotations__))
        self.assertEqual(set(adv["urdu"]), set(UrduAdvisory.__annotations__))
        self.assertEqual(set(adv["audiences"]), set(AUDIENCES))
        self.assertIsInstance(adv["headline"], str)
        self.assertTrue(all(isinstance(a, str) for a in adv["actions"]))

    def test_all_mock_scenarios_end_to_end(self):
        # Monitor (mock) -> Analysis -> Advisory -> Alert, for every scenario in data/mock_readings.json
        for scenario in LEVELS + ["spike"]:
            with self.subTest(scenario=scenario):
                alert.reset_memory()  # each scenario starts fresh, or an earlier alert hides this one
                state = {"readings": monitor.mock_readings("Lahore", scenario)}
                state.update(analysis.run(state))
                state.update(advisory.run(state))
                state.update(alert.run(state))
                level = state["analysis"]["level"]
                if scenario != "spike":
                    self.assertEqual(level, scenario)
                self.assertEqual(state["advisory"]["headline"], advisory.GUIDANCE[level]["headline"])
                if level in {"very_poor", "severe"}:
                    self.assertEqual(state["alerts"][0]["severity"], "critical")
                    self.assertIn(state["advisory"]["headline"], state["alerts"][0]["message"])


# ---------- forecast wording ----------

from datetime import datetime, timedelta, timezone  # noqa: E402

from agents import forecast as forecast_agent  # noqa: E402

NOW = datetime(2026, 10, 17, 10, 30, tzinfo=timezone.utc)   # 15:30 local (UTC+5)
HOUR0 = NOW.replace(minute=0)


def make_forecast(values: list[float]) -> dict:
    """A forecast whose hour N (from the current hour, 10:00 UTC = 15:00 local) has PM2.5 values[N]."""
    points = [{"time": (HOUR0 + timedelta(hours=h)).isoformat(), "pm25": float(v)} for h, v in enumerate(values)]
    return forecast_agent._forecast_from_series("Lahore", {"offset": 5 * 3600, "points": points}, "live", NOW)


def note_for(level: str, values: list[float]) -> dict:
    return advisory.build_advisory(make_analysis(level), make_forecast(values))


class ForecastWordingTest(unittest.TestCase):
    def test_worsening_within_6_hours(self):
        result = note_for("satisfactory", [30, 40, 130, 150, 150, 150] + [30] * 18)   # Poor from hour 2 = 17:00 local
        self.assertEqual(result["forecast_note"].split(" Best time")[0],
                         "Air quality is forecast to worsen over the next 6 hours, reaching Poor around 17:00; "
                         "plan indoor activities.")
        self.assertTrue(result["urdu"]["forecast_note"].startswith(
            "اگلے 6 گھنٹوں میں ہوا کا معیار خراب ہونے کی پیش گوئی ہے، تقریباً 17:00 تک خراب"))

    def test_slightly_worse_in_good_air(self):
        result = note_for("good", [5, 6, 8, 12, 15, 15] + [5] * 18)            # good -> satisfactory only
        self.assertEqual(result["forecast_note"], advisory.SLIGHTLY_WORSE_NOTE[0])  # no "best time" in good air
        self.assertEqual(result["urdu"]["forecast_note"], advisory.SLIGHTLY_WORSE_NOTE[1])

    def test_improves_by_tomorrow_morning(self):
        values = [150] * 16 + [20] * 8                                        # better from hour 16 = 07:00 local tomorrow
        result = note_for("poor", values)
        self.assertTrue(result["forecast_note"].startswith("Expected to improve by tomorrow morning."))
        self.assertTrue(result["urdu"]["forecast_note"].startswith("کل صبح تک بہتری کی توقع ہے۔"))

    def test_improves_this_evening(self):
        result = note_for("poor", [150, 150, 150, 20] + [20] * 20)       # hour 3 = 18:00 local today
        self.assertTrue(result["forecast_note"].startswith("Expected to improve by this evening."))
        self.assertTrue(result["urdu"]["forecast_note"].startswith("آج شام تک بہتری کی توقع ہے۔"))

    def test_not_improving_and_no_clean_window(self):
        result = note_for("poor", [150] * 24)
        self.assertEqual(result["forecast_note"],
                         "Not expected to improve in the next 24 hours. "
                         "Even the cleanest hours in the next 24 hours stay Poor; limit time outdoors.")
        self.assertEqual(result["urdu"]["forecast_note"],
                         "اگلے 24 گھنٹوں میں بہتری کی توقع نہیں۔ "
                         "اگلے 24 گھنٹوں کے صاف ترین اوقات بھی خراب رہیں گے؛ باہر کم وقت گزاریں۔")

    def test_best_time_to_go_outside(self):
        values = [30] * 15 + [12, 12] + [30] * 7                              # hours 15-16 = 06:00-08:00 local tomorrow
        result = note_for("satisfactory", values)
        self.assertEqual(result["forecast_note"], "Best time to go outside: tomorrow 06:00–08:00.")
        self.assertEqual(result["urdu"]["forecast_note"], "باہر جانے کا بہترین وقت: کل 06:00–08:00۔")

    def test_best_time_later_today_has_no_day(self):
        values = [30, 30, 30, 12, 12] + [30] * 19                             # hours 3-4 = 18:00-20:00 local today
        result = note_for("satisfactory", values)
        self.assertEqual(result["forecast_note"], "Best time to go outside: 18:00–20:00.")
        self.assertEqual(result["urdu"]["forecast_note"], "باہر جانے کا بہترین وقت: 18:00–20:00۔")

    def test_wording_at_every_level_in_english_and_urdu(self):
        # Each level gets a forecast that worsens (or, at the top, improves) so the note has to speak
        cases = {
            "good": ([5] + [15] * 23, advisory.SLIGHTLY_WORSE_NOTE),
            "satisfactory": ([30] + [80] * 23, advisory.WORSEN_NOTE),
            "moderate": ([45] + [150] * 23, advisory.WORSEN_NOTE),
            "poor": ([150] + [250] * 23, advisory.WORSEN_NOTE),
            "very_poor": ([250] + [320] * 23, advisory.WORSEN_NOTE),
            "severe": ([300] * 3 + [100] * 21, advisory.IMPROVE_NOTE),
        }
        self.assertEqual(list(cases), LEVELS)
        for level, (values, template) in cases.items():
            with self.subTest(level=level):
                result = note_for(level, values)
                english, urdu = result["forecast_note"], result["urdu"]["forecast_note"]
                self.assertTrue(english.startswith(template[0].split("{")[0]), english)
                self.assertTrue(urdu.startswith(template[1].split("{")[0]), urdu)
                self.assertIn(english, result["actions"])                     # also listed for the dashboard
                self.assertIn(urdu, result["urdu"]["actions"])
                self.assertIn(advisory.DISCLAIMER_UR, result["urdu"]["actions"])
                self.assertIn("not medical advice", result["disclaimer"])

    def test_forecast_never_changes_the_advice_or_its_severity(self):
        for level in LEVELS:
            with self.subTest(level=level):
                plain = advisory.build_advisory(make_analysis(level))
                with_forecast = note_for(level, [300] * 24)
                self.assertEqual(plain["headline"], with_forecast["headline"])
                self.assertEqual(plain["audiences"], with_forecast["audiences"])
                self.assertEqual(plain["disclaimer"], with_forecast["disclaimer"])

    def test_note_comes_after_the_time_note(self):
        result = advisory.build_advisory(make_analysis("poor", trend="rising"), make_forecast([80] * 24))
        self.assertEqual(result["actions"][:2], [result["time_note"], result["forecast_note"]])

    def test_no_forecast_no_note(self):
        for missing in (None, {}, {"next_6h": None}):
            with self.subTest(forecast=missing):
                result = advisory.build_advisory(make_analysis("poor"), missing)
                self.assertEqual((result["forecast_note"], result["urdu"]["forecast_note"]), ("", ""))

    def test_unknown_level_gets_no_forecast_note(self):
        result = advisory.build_advisory({"level": "unknown"}, make_forecast([300] * 24))
        self.assertEqual(result["forecast_note"], "")

    def test_malformed_forecast_never_raises(self):
        for bad in ({"next_6h": {"peak_level": "satisfactory"}, "generated_at": "x"}, {"next_6h": "nonsense"},
                    {"next_6h": {"peak_level": "poor", "peak_time": "not a time"}}):
            with self.subTest(forecast=bad):
                result = advisory.build_advisory(make_analysis("satisfactory"), bad)
                self.assertEqual(set(result), set(Advisory.__annotations__))

    def test_pipeline_passes_the_forecast_through(self):
        readings = monitor.mock_readings("Lahore", "moderate")
        state = {
            "readings": readings,
            "forecast": forecast_agent.mock_forecast("Lahore", readings[-1]["pm25"], scenario="moderate"),
        }
        state.update(analysis.run(state))
        result = advisory.run(state)["advisory"]
        self.assertTrue(result["forecast_note"].startswith("Air quality is forecast to worsen over the next 6 hours"))


if __name__ == "__main__":
    unittest.main()
