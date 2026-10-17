"""Tests for the graph.py self-check: it must never send real messages or touch the real alert feed.

Run from the smogshield folder:  python -m unittest discover tests -v
"""
import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "var" / "alerts.json"


@unittest.skipUnless(importlib.util.find_spec("langgraph"), "langgraph not installed (pip install -r requirements.txt)")
class SelfCheckTest(unittest.TestCase):
    def test_self_check_sends_nothing_and_leaves_var_alone(self):
        before = STORE.stat().st_mtime_ns if STORE.exists() else None
        env = {
            **os.environ,
            "MOCK_SCENARIO": "hazardous",              # guarantees a critical alert is raised
            "ALERT_SIMULATIONS_TO_TELEGRAM": "true",   # so only the self-check's own guard can stop it
            "TELEGRAM_BOT_TOKEN": "123456:FAKE-TOKEN",
            "TELEGRAM_CHAT_ID": "42",
            "HTTPS_PROXY": "http://127.0.0.1:9",      # belt and braces: nothing can leave this machine
            "PYTHONIOENCODING": "utf-8",
        }
        result = subprocess.run([sys.executable, "graph.py"], cwd=ROOT, env=env,
                                capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK", result.stdout)
        self.assertIn("'severity': 'critical'", result.stdout)              # an alert was raised...
        self.assertIn("'channel': 'feed', 'status': 'sent'", result.stdout)  # ...and kept in the feed
        self.assertNotIn("queued", result.stdout)
        self.assertNotIn("FAKE-TOKEN", result.stdout + result.stderr)
        after = STORE.stat().st_mtime_ns if STORE.exists() else None
        self.assertEqual(before, after, "the self-check must not write var/alerts.json")


if __name__ == "__main__":
    unittest.main()
