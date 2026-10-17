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
        os.environ["MOCK_SCENARIO"] = "moderate"  # mock data: no network needed
        self.assertEqual(app.monitor.run({})["readings"][-1]["location"], "Karachi")

    def test_unknown_city_is_404_and_changes_nothing(self):
        app.set_city("Multan")
        with self.assertRaises(app.HTTPException) as caught:
            app.set_city("Atlantis")
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(app.get_city()["current"], "Multan")

    def test_unknown_env_city_reports_default(self):
        os.environ["MONITOR_CITY"] = "Atlantis"
        self.assertEqual(app.get_city()["current"], "Lahore")

    def test_scenario_round_trip(self):
        self.assertEqual(app.set_scenario("hazardous")["current"], "hazardous")
        self.assertEqual(app.set_scenario("live")["current"], "live")
        with self.assertRaises(app.HTTPException):
            app.set_scenario("bogus")


if __name__ == "__main__":
    unittest.main()
