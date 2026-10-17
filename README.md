# SmogShield

A modular multi-agent system that monitors air quality and coordinates smog response in real time.

```
monitor ──► analysis ──► advisory ──► alert ──► dashboard
(Open-Meteo (AQI, level,  (public      (warning /
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
cp .env.example .env          # optional, see Configuration below (Windows: copy .env.example .env)
python graph.py               # self-check, should print OK
uvicorn app:app --reload      # open http://localhost:8000
```

By default the app uses live data for Lahore. If the network is down, it replays `data/mock_readings.json`, a scripted smog spike that advances every 5 seconds.

## Project layout

| Path | What it is |
|------|-----------|
| `schemas.py` | Contracts between agents. Change these as a team. |
| `agents/monitor.py` | Fetches readings from Open-Meteo, falls back to mock data |
| `agents/analysis.py` | PM2.5 → US EPA AQI, level, trend |
| `agents/advisory.py` | Level → public guidance |
| `agents/alert.py` | Decides whether to alert and how loudly |
| `graph.py` | LangGraph orchestrator + self-check |
| `app.py` | FastAPI server: `/` dashboard, `/api/status` runs the pipeline |
| `web/index.html` | Dashboard (plain HTML/JS, no build step) |
| `data/mock_readings.json` | Demo data |

## Configuration

Settings live in `.env`, which `app.py` and `graph.py` load at startup. Copy `.env.example` to `.env` and edit it. **Never commit `.env`**; it is gitignored. All settings are optional, and no API keys are needed.

| Variable | Default | What it does |
|----------|---------|--------------|
| `USE_MOCK` | `false` | `true` skips the network and always uses `data/mock_readings.json`. |
| `MONITOR_CITY` | `Lahore` | City to watch: Lahore, Karachi, Islamabad, Rawalpindi, Faisalabad, Multan, Peshawar, Quetta, Gujranwala, Sialkot. |
| `MOCK_SCENARIO` | unset | Forces mock data for one scenario: `good`, `moderate`, `unhealthy_sensitive`, `unhealthy`, `very_unhealthy`, `hazardous`, `spike`. |

**Demo tip:** set `MOCK_SCENARIO=hazardous` to force a smog emergency on stage. Use `spike` to show air building from clean to hazardous and back. Restart the server after editing `.env`.

Live data: air quality data from [Open-Meteo](https://open-meteo.com) (free, no key, non-commercial use), based on CAMS ENSEMBLE data from the Copernicus Atmosphere Monitoring Service. If a live call fails or takes more than 10 s, the monitor falls back to mock data.

## Adding an agent

1. Create `agents/<name>.py` with `def run(state: SmogState) -> dict:` that returns only the keys it owns.
2. Add its output type and state key in `schemas.py`.
3. Add a node and edge in `graph.py`.
