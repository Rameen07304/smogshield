"""Web server: runs the agent pipeline and serves the dashboard.

Start: uvicorn app:app --reload
Then open http://localhost:8000
"""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # must run before agents read env vars

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402

from graph import run_once  # noqa: E402

app = FastAPI(title="SmogShield")
INDEX = Path(__file__).parent / "web" / "index.html"


@app.get("/")
def dashboard():
    return FileResponse(INDEX)


@app.get("/api/status")
def status():
    """One full pass through all agents. The dashboard polls this."""
    return run_once()
