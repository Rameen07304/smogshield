"""Web server: runs the agent pipeline and serves the dashboard.

Start: uvicorn app:app --reload
Then open http://localhost:8000
"""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # must run before agents read env vars
# Show agents' INFO logs (e.g. every "ALERT ..." line) next to uvicorn's own output
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from agents import alert, monitor  # noqa: E402
from graph import run_once  # noqa: E402

app = FastAPI(title="SmogShield")
WEB = Path(__file__).parent / "web"
INDEX = WEB / "index.html"
app.mount("/static", StaticFiles(directory=WEB), name="static")  # dashboard CSS, JS and fonts


@app.get("/")
def dashboard():
    return FileResponse(INDEX)


@app.get("/api/status")
def status():
    """One full pass through all agents. The dashboard polls this."""
    return run_once()


@app.get("/api/alerts")
def alert_feed(limit: int = 20):
    """Alert feed, newest first (from var/alerts.json)."""
    return alert.read_feed(limit)


@app.get("/api/scenario")
def get_scenario():
    """The forced mock scenario ("live" = none) and the options for the dashboard's demo control."""
    return {"current": os.getenv("MOCK_SCENARIO") or "live", "options": ["live", *_mock_scenarios()]}


@app.post("/api/scenario/{name}")
def set_scenario(name: str):
    """Demo control: force a mock scenario, or "live" to go back. Lasts until the server restarts."""
    if name == "live":
        os.environ.pop("MOCK_SCENARIO", None)
    elif name in _mock_scenarios():
        os.environ["MOCK_SCENARIO"] = name
    else:
        raise HTTPException(404, f"Unknown scenario {name!r}")
    alert.reset_memory()  # so the new scenario's alerts show up right away
    return get_scenario()


def _mock_scenarios() -> list[str]:
    return monitor.mock_scenarios()  # never raises: falls back to a built-in scenario
