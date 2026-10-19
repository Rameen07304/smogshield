"""Tests for the app's control endpoints (city and scenario). Calls the route functions directly.

Run from the smogshield folder:  python -m unittest discover tests -v
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

app = None


def setUpModule():
    global app
    if not importlib.util.find_spec("langgraph"):
        return
    # Importing app must not read the developer's .env or reconfigure logging for the whole test run
    with mock.patch("dotenv.load_dotenv"), mock.patch("logging.basicConfig"):
        import app as app_module
    app = app_module


@unittest.skipUnless(importlib.util.find_spec("langgraph"), "langgraph not installed (pip install -r requirements.txt)")
class ControlEndpointTest(unittest.TestCase):
    def setUp(self):
        drop = {"MONITOR_CITY", "MOCK_SCENARIO"}
        env_patch = mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k not in drop}, clear=True)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store_patch = mock.patch.object(app.alert, "STORE_FILE", Path(tmp.name) / "alerts.json")
        store_patch.start()
        self.addCleanup(store_patch.stop)

    def test_get_city_defaults_to_lahore_and_lists_known_cities(self):
        result = app.get_city()
        self.assertEqual(result["current"], "Lahore")
        self.assertEqual(result["options"], list(app.monitor.CITIES))

    def test_set_city_any_case(self):
        self.assertEqual(app.set_city("karachi")["current"], "Karachi")
        self.assertEqual(os.environ["MONITOR_CITY"], "Karachi")
        os.environ["MOCK_SCENARIO"] = "satisfactory"  # mock data: no network needed
        self.assertEqual(app.monitor.run({})["readings"][-1]["location"], "Karachi")

    def test_ask_rejects_blank_and_overlong_questions(self):
        with self.assertRaises(app.HTTPException) as caught:
            app.ask(app.Question(question="   "))
        self.assertEqual(caught.exception.status_code, 422)
        with self.assertRaises(ValueError):  # pydantic's ValidationError is a ValueError
            app.Question(question="x" * 301)

    def test_ask_answers_from_a_fresh_pipeline_run(self):
        os.environ["MOCK_SCENARIO"] = "poor"  # mock data: no network needed
        with mock.patch.object(app.advisory, "answer_question", return_value={"answer": "ok", "source": "ai"}) as ask:
            self.assertEqual(app.ask(app.Question(question=" Is it safe? ")), {"answer": "ok", "source": "ai"})
        question, state = ask.call_args.args
        self.assertEqual(question, "Is it safe?")
        self.assertEqual(state["analysis"]["level"], "poor")

    def test_cities_summary_lists_every_city_once(self):
        os.environ["USE_MOCK"] = "true"  # no network
        result = app.cities_summary()
        self.assertEqual([c["city"] for c in result["cities"]], list(app.monitor.CITIES))
        for c in result["cities"]:
            self.assertIn(c["level"], app.analysis.HAZARDOUS_LEVELS | {"good", "satisfactory", "moderate"})
            self.assertEqual(c["source"], "mock")

    def test_forced_scenario_only_changes_the_monitored_city(self):
        app.set_city("Quetta")
        os.environ["MOCK_SCENARIO"] = "severe"
        os.environ["USE_MOCK"] = "true"  # no network for the 7-day strip
        levels = {c["city"]: c["level"] for c in app.cities_summary()["cities"]}
        self.assertEqual(levels["Quetta"], "severe")
        self.assertEqual(levels["Karachi"], app.monitor.city_default_scenario("Karachi"))  # its own default, not severe

    def test_unknown_city_is_404_and_changes_nothing(self):
        app.set_city("Multan")
        with self.assertRaises(app.HTTPException) as caught:
            app.set_city("Atlantis")
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(app.get_city()["current"], "Multan")

    def test_unknown_env_city_reports_default(self):
        os.environ["MONITOR_CITY"] = "Atlantis"
        self.assertEqual(app.get_city()["current"], "Lahore")

    def test_both_pages_are_served(self):
        for page in (app.dashboard(), app.how_it_works(), app.alert_history()):
            with self.subTest(path=page.path):
                self.assertTrue(Path(page.path).is_file())

    def test_status_includes_the_forecast_for_every_scenario(self):
        from schemas import Forecast
        for scenario in app._mock_scenarios():
            with self.subTest(scenario=scenario):
                app.set_scenario(scenario)
                result = app.status()
                forecast = result["forecast"]
                self.assertEqual(set(forecast), set(Forecast.__annotations__))
                self.assertEqual(forecast["source"], "mock")
                self.assertEqual(forecast["location"], result["readings"][-1]["location"])
                self.assertEqual(forecast["hourly"][0]["pm25"], result["readings"][-1]["pm25"])  # anchored on now
                self.assertEqual(len(forecast["hourly"]), 24)
                self.assertIsNotNone(forecast["next_6h"])

    def test_scenario_round_trip(self):
        self.assertEqual(app.set_scenario("severe")["current"], "severe")
        self.assertEqual(app.set_scenario("live")["current"], "live")
        with self.assertRaises(app.HTTPException):
            app.set_scenario("bogus")


if __name__ == "__main__":
    unittest.main()
