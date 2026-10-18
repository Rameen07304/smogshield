"""Tests for the graph.py self-check: it must never send real messages or touch the real alert feed.

Run from the smogshield folder:  python -m unittest discover tests -v
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(importlib.util.find_spec("langgraph"), "langgraph not installed (pip install -r requirements.txt)")
class SelfCheckTest(unittest.TestCase):
    def test_self_check_sends_nothing_and_leaves_var_alone(self):
        # Run graph.py in a private copy of the project: a dashboard server running at the same time
        # writes the real var/alerts.json, which would make "did the self-check write it?" unanswerable.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        project = Path(tmp.name)
        for name in ("graph.py", "schemas.py"):
            shutil.copy2(ROOT / name, project / name)
        for folder in ("agents", "data"):
            shutil.copytree(ROOT / folder, project / folder, ignore=shutil.ignore_patterns("__pycache__"))
        store = project / "var" / "alerts.json"
        env = {
            **os.environ,
            "MOCK_SCENARIO": "severe",              # guarantees a critical alert is raised
            "ALERT_SIMULATIONS_TO_TELEGRAM": "true",   # so only the self-check's own guard can stop it
            "TELEGRAM_BOT_TOKEN": "123456:FAKE-TOKEN",
            "TELEGRAM_CHAT_ID": "42",
            "HTTPS_PROXY": "http://127.0.0.1:9",      # belt and braces: nothing can leave this machine
            "PYTHONIOENCODING": "utf-8",
        }
        result = subprocess.run([sys.executable, "graph.py"], cwd=project, env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stdout)
        self.assertIn("'severity': 'critical'", result.stdout)              # an alert was raised...
        self.assertIn("'channel': 'feed', 'status': 'sent'", result.stdout)  # ...and kept in the feed
        self.assertNotIn("queued", result.stdout)
        self.assertNotIn("FAKE-TOKEN", result.stdout + result.stderr)
        self.assertFalse(store.exists(), "the self-check must not write var/alerts.json")


if __name__ == "__main__":
    unittest.main()
