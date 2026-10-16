# SmogShield

A modular multi-agent system that monitors air quality and coordinates smog response in real time.

```
monitor ──► analysis ──► advisory ──► alert ──► dashboard
(OpenAQ /   (AQI, level,  (public      (warning /
 mock data)  trend)        guidance)    critical)
```

Agents are plain Python functions wired together with [LangGraph](https://github.com/langchain-ai/langgraph).
They share one state object defined in [`schemas.py`](schemas.py). Each agent writes only its own key.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional: leave empty to use mock data
python graph.py               # self-check, should print OK
uvicorn app:app --reload      # open http://localhost:8000
```

With no API key, the app replays `data/mock_readings.json`, a scripted smog spike that advances every 5 seconds.

## Project layout

| Path | What it is |
|------|-----------|
| `schemas.py` | Contracts between agents. Change these as a team. |
| `agents/monitor.py` | Fetches readings from OpenAQ, falls back to mock data |
| `agents/analysis.py` | PM2.5 → US EPA AQI, level, trend |
| `agents/advisory.py` | Level → public guidance |
| `agents/alert.py` | Decides whether to alert and how loudly |
| `graph.py` | LangGraph orchestrator + self-check |
| `app.py` | FastAPI server: `/` dashboard, `/api/status` runs the pipeline |
| `web/index.html` | Dashboard (plain HTML/JS, no build step) |
| `data/mock_readings.json` | Demo data |

## Using real data (OpenAQ)

1. Get a free API key at https://explore.openaq.org (sign in → API key).
2. Find a location id with a PM2.5 sensor on the OpenAQ explorer.
3. Put both in `.env`. **Never commit `.env`**; it is gitignored.

## Adding an agent

1. Create `agents/<name>.py` with `def run(state: SmogState) -> dict:` that returns only the keys it owns.
2. Add its output type and state key in `schemas.py`.
3. Add a node and edge in `graph.py`.
