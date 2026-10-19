"""Web server: runs the agent pipeline and serves the dashboard.

Start: uvicorn app:app --reload
Then open http://localhost:8000
"""
import logging
import os
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # must run before agents read env vars
# Show agents' INFO logs (e.g. every "ALERT ..." line) next to uvicorn's own output
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agents import advisory, alert, analysis, monitor  # noqa: E402
from graph import run_once  # noqa: E402

app = FastAPI(title="SmogShield")
WEB = Path(__file__).parent / "web"
INDEX = WEB / "index.html"
app.mount("/static", StaticFiles(directory=WEB), name="static")  # dashboard CSS, JS and fonts

# On a public link everyone shares one server, so a demo change (scenario or city) goes back to live data for
# the starting city after DEMO_RESET_MINUTES. 0 or unset = never (the default, for a laptop demo).
START_CITY = os.getenv("MONITOR_CITY", monitor.DEFAULT_CITY)
_demo_changed_at: float | None = None
# Ask SmogShield: at most ASK_PER_MINUTE questions per visitor, so one visitor can't use up the Groq quota
ASK_PER_MINUTE = 6
_asked: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def always_fresh_pages(request, call_next):
    """Browsers must revalidate pages and static files (a cheap 304 when unchanged), so after a git pull
    or a restart nobody runs an old common.js next to a new app.js."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/")
def dashboard():
    return FileResponse(INDEX)


@app.get("/how")
def how_it_works():
    """Screen 2: explains the agent pipeline, with a live example."""
    return FileResponse(WEB / "how.html")


@app.get("/history")
def alert_history():
    """Screen 3: table of past alerts (reads /api/alerts; the store keeps the newest 100)."""
    return FileResponse(WEB / "history.html")


@app.get("/blog")
def blog():
    """Screen 4: smog guides for each group, what to avoid and how to improve the air (static, English and Urdu)."""
    return FileResponse(WEB / "blog.html")


@app.get("/api/status")
def status():
    """One full pass through all agents. The dashboard polls this."""
    _expire_demo()
    return run_once()


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=advisory.ASK_MAX_CHARS)


@app.post("/api/ask")
def ask(body: Question, request: Request = None):
    """Ask SmogShield: one question, answered by Groq from a fresh pipeline run (off unless LLM is enabled)."""
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "Ask a question about the air")
    if request is not None and _too_many_questions(_visitor(request)):
        return {"answer": advisory.ASK_BUSY[bool(advisory.URDU_SCRIPT.search(question))], "source": "busy"}
    return advisory.answer_question(question, run_once())


@app.get("/api/alerts")
def alert_feed(limit: int = 20):
    """Alert feed, newest first (from var/alerts.json)."""
    return alert.read_feed(limit)


@app.get("/api/scenario")
def get_scenario():
    """The forced mock scenario ("live" = none) and the options for the dashboard's demo control."""
    _expire_demo()
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
    _demo_changed()
    return get_scenario()


@app.get("/api/city")
def get_city():
    """The monitored city and the known cities, for the dashboard's city selector."""
    current = _known_city(os.getenv("MONITOR_CITY", monitor.DEFAULT_CITY)) or monitor.DEFAULT_CITY
    return {"current": current, "options": list(monitor.CITIES), "labels_ur": monitor.CITIES_UR}


@app.post("/api/city/{name}")
def set_city(name: str):
    """Switch the monitored city (one of monitor.CITIES, any case). Lasts until the server restarts."""
    city = _known_city(name)
    if city is None:
        raise HTTPException(404, f"Unknown city {name!r}")
    os.environ["MONITOR_CITY"] = city
    _demo_changed()
    return get_city()


@app.get("/api/cities")
def cities_summary():
    """Every city's latest AQI and level, for the map. Live readings are cached per city (10 min), fetched in
    parallel. With a demo scenario forced, only the monitored city shows it; the others show their own
    simulated default, so the map stays varied and is still labelled simulated."""
    current = get_city()["current"]
    forced = monitor._mock_requested()

    def one(city: str) -> dict:
        if forced:
            scenario = os.getenv("MOCK_SCENARIO") if city == current else monitor.city_default_scenario(city)
            reading = monitor.fetch_air_quality(city, scenario=scenario or None)
        else:
            reading = monitor.fetch_air_quality(city)
        a = analysis.assess([reading])
        lat, lon = monitor.CITIES[city]
        return {"city": city, "lat": lat, "lon": lon, "aqi": a["aqi"], "level": a["level"], "source": reading["source"],
                "past_days": monitor.past_days(city)}  # always real past data, even in a demo scenario

    with ThreadPoolExecutor(max_workers=8) as pool:
        return {"current": current, "cities": list(pool.map(one, monitor.CITIES))}


def _demo_changed() -> None:
    global _demo_changed_at
    _demo_changed_at = time.monotonic()


def _expire_demo() -> None:
    """Back to live data for the starting city once a demo change is DEMO_RESET_MINUTES old."""
    global _demo_changed_at
    minutes = monitor.env_minutes("DEMO_RESET_MINUTES", 0)
    if not minutes or _demo_changed_at is None or time.monotonic() - _demo_changed_at < minutes * 60:
        return
    _demo_changed_at = None
    os.environ.pop("MOCK_SCENARIO", None)
    os.environ["MONITOR_CITY"] = START_CITY
    alert.reset_memory()
    logging.getLogger(__name__).info("Demo reset: back to live data for %s", START_CITY)


def _visitor(request: Request) -> str:
    """The visitor's address. Behind a host's proxy it's the first X-Forwarded-For entry."""
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")


def _too_many_questions(visitor: str) -> bool:
    """True when this visitor already asked ASK_PER_MINUTE questions in the last minute."""
    # ponytail: in-memory and per process, fine for one worker; a shared store if this ever scales out
    now, asked = time.monotonic(), _asked[visitor]
    while asked and now - asked[0] > 60:
        asked.popleft()
    if len(asked) >= ASK_PER_MINUTE:
        return True
    asked.append(now)
    return False


def _known_city(name: str) -> str | None:
    """The canonical spelling of a known city, or None."""
    return next((city for city in monitor.CITIES if city.lower() == name.strip().lower()), None)


def _mock_scenarios() -> list[str]:
    return monitor.mock_scenarios()  # never raises: falls back to a built-in scenario
