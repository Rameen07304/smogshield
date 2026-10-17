"""Tests for the advisory agent. Pure functions, no network.

Run from the smogshield folder:  python -m unittest discover tests -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import advisory, alert, analysis, monitor  # noqa: E402
from schemas import Advisory, Audience, UrduAdvisory  # noqa: E402

LEVELS = ["good", "moderate", "unhealthy_sensitive", "unhealthy", "very_unhealthy", "hazardous"]
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


class SeverityTest(unittest.TestCase):
    def test_masks_only_from_unhealthy_up(self):
        for level in LEVELS:
            with self.subTest(level=level):
                says_mask = "mask" in all_text(advisory.build_advisory(make_analysis(level)))
                self.assertEqual(says_mask, level in {"unhealthy", "very_unhealthy", "hazardous"})

    def test_hazardous_says_stay_indoors_and_good_does_not(self):
        hazardous = advisory.build_advisory(make_analysis("hazardous"))
        good = advisory.build_advisory(make_analysis("good"))
        self.assertIn("stay indoors", " ".join(hazardous["audiences"]["general"]).lower())
        for word in ("indoors", "mask", "avoid", "reduce"):
            self.assertNotIn(word, all_text(good))

    def test_sensitive_groups_get_warned_before_the_public(self):
        usg = advisory.build_advisory(make_analysis("unhealthy_sensitive"))
        self.assertIn("reduce", " ".join(usg["audiences"]["respiratory_heart"]).lower())
        self.assertIn("most people can continue", " ".join(usg["audiences"]["general"]).lower())

    def test_general_advice_grows_with_severity(self):
        # A rough monotonic check: more severe levels never give fewer public actions
        counts = [len(advisory.GUIDANCE[level]["general"]) for level in LEVELS]
        self.assertEqual(counts, sorted(counts))


class TimeContextTest(unittest.TestCase):
    def test_spike_note_comes_first(self):
        result = advisory.build_advisory(make_analysis("moderate", trend="rising", is_spike=True))
        self.assertEqual(result["time_note"], advisory.SPIKE_NOTE[0])
        self.assertEqual(result["actions"][0], advisory.SPIKE_NOTE[0])
        self.assertEqual(result["urdu"]["actions"][0], advisory.SPIKE_NOTE[1])

    def test_rising(self):
        result = advisory.build_advisory(make_analysis("unhealthy", trend="rising"))
        self.assertIn("worsening", result["time_note"])
        self.assertEqual(result["actions"][0], result["time_note"])

    def test_falling(self):
        self.assertIn("improving", advisory.build_advisory(make_analysis("unhealthy", trend="falling"))["time_note"])

    def test_stable_has_no_note(self):
        result = advisory.build_advisory(make_analysis("unhealthy"))
        self.assertEqual(result["time_note"], "")
        self.assertEqual(result["actions"], result["audiences"]["general"])

    def test_rising_in_good_air_has_no_note(self):
        self.assertEqual(advisory.build_advisory(make_analysis("good", trend="rising"))["time_note"], "")

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

    def test_run_without_analysis(self):
        self.assertEqual(advisory.run({})["advisory"]["headline"], advisory.FALLBACK_HEADLINE)

    def test_output_does_not_share_the_template_lists(self):
        result = advisory.build_advisory(make_analysis("hazardous"))
        result["audiences"]["general"].append("mutated")
        self.assertNotIn("mutated", advisory.GUIDANCE["hazardous"]["general"])


class ContractTest(unittest.TestCase):
    def setUp(self):
        # The alert agent remembers past alerts in a file; use a fresh temp one per test
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store_patch = mock.patch.object(alert, "STORE_FILE", Path(tmp.name) / "alerts.json")
        store_patch.start()
        self.addCleanup(store_patch.stop)

    def test_matches_schema(self):
        result = advisory.run({"analysis": make_analysis("unhealthy", trend="rising")})
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
                if level in {"very_unhealthy", "hazardous"}:
                    self.assertEqual(state["alerts"][0]["severity"], "critical")
                    self.assertIn(state["advisory"]["headline"], state["alerts"][0]["message"])


if __name__ == "__main__":
    unittest.main()
