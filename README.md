# SmogShield

A modular multi-agent system that monitors air quality and coordinates smog response in real time.

```
monitor ──► forecast ──► analysis ──► advisory ──► alert ──► dashboard
(Open-Meteo (next 24 h,  (AQI, level,  (public      (feed /
 mock data)  best time,   trend,       guidance,    Telegram,
             outlook)     spike)       Urdu)        [FORECAST])
```

Agents are plain Python functions wired together with [LangGraph](https://github.com/langchain-ai/langgraph).
They share one state object defined in [`schemas.py`](schemas.py). Each agent writes only its own key.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                  # optional, see Configuration (Windows: copy .env.example .env)
python -m unittest discover tests -v  # all tests, no network needed
python graph.py                       # self-check, should print OK
uvicorn app:app --reload              # open http://localhost:8000
```

By default the app uses live data for Lahore. If the network is down, it falls back to `data/mock_readings.json` and the dashboard says so with a **SIMULATED DATA** banner.

## Running the server safely

- **Run uvicorn on 127.0.0.1 only** (its default, as in the command above). **Never use `--host 0.0.0.0`**: the API has no login, so anyone on the same Wi-Fi could switch the demo scenario or trigger the pipeline.
- **Use a single worker** (the default; never pass `--workers`). Alert memory and the feed live in one file, `var/alerts.json`, guarded by an in-process lock, and the demo scenario control changes the running process. Several workers would each keep their own state and could send duplicate alerts.
- Restart the server after editing `.env`; it is only read at startup.

## Tests

```bash
python -m unittest discover tests -v
```

The tests need no network and never send real messages: they clear `TELEGRAM_*` and fake every HTTP call. `python graph.py` is a self-check that runs the whole pipeline once; it also never sends to Telegram and never writes the real alert feed. Run both before every PR.

## Project layout

| Path | What it is |
|------|-----------|
| `schemas.py` | Contracts between agents. Change these as a team. |
| `agents/monitor.py` | Fetches the last 6 hours from Open-Meteo, falls back to mock data |
| `agents/forecast.py` | Hourly PM2.5 forecast from Open-Meteo: next 24 h (AQI, level, confidence), 6 h and 24 h summaries, best ~2-hour window to go outside, multi-day outlook; falls back to a scripted mock forecast |
| `agents/analysis.py` | PM2.5 → AQI estimate, level, trend, spike flag |
| `agents/advisory.py` | Level and forecast → guidance per audience, plus a forecast note (+ Urdu) |
| `agents/alert.py` | Decides whether to alert, how loudly, and delivers it, including predictive `[FORECAST]` alerts |
| `graph.py` | LangGraph orchestrator + self-check |
| `app.py` | FastAPI server: dashboard and API (below) |
| `web/` | Dashboard: `index.html`, `styles.css`, `app.js` (plain HTML/CSS/JS, no build step, no CDNs) and `fonts/` (Noto Nastaliq Urdu, SIL Open Font License) |
| `data/mock_readings.json` | Demo scenarios |
| `data/mock_forecasts.json` | Scripted forecast curve per demo scenario (multipliers of the current PM2.5 by hours ahead) |
| `tests/` | Unit and end-to-end tests |
| `var/` | Runtime data, created on first alert, gitignored: `var/alerts.json` holds the alert feed and alert memory. Delete it to start with an empty feed. |

## API

| Method and path | What it does |
|-----------------|--------------|
| `GET /` | The live dashboard (Screen 1) |
| `GET /how` | How it works (Screen 2): the agent pipeline, a live example, data honesty and safeguards |
| `GET /api/status` | Runs the whole pipeline once and returns `readings`, `forecast`, `analysis`, `advisory`, `alerts` (new alerts from this run). The dashboard polls it every 5 s. |
| `GET /api/alerts?limit=20` | The alert feed, newest first |
| `GET /api/scenario` | The forced mock scenario (`live` = none) and the list of options |
| `POST /api/scenario/{name}` | Demo control: force a scenario, or `live` to go back. Also clears the alert memory so the new scenario alerts right away. Lasts until the server restarts. |
| `GET /api/city` | The monitored city and the list of known cities |
| `POST /api/city/{name}` | Switch the monitored city (any case; unknown names give 404). Lasts until the server restarts. |
| `GET /static/...` | Dashboard files from `web/` |

Open the dashboard in Urdu with `http://localhost:8000/?lang=ur` (the language toggle is remembered per browser).

## Configuration

Settings live in `.env`, which `app.py` and `graph.py` load at startup. Copy `.env.example` to `.env` and edit it. **Never commit `.env`**; it is gitignored. Every setting is optional, and no API keys are needed for live data.

### Data (monitor)

| Variable | Default | What it does |
|----------|---------|--------------|
| `USE_MOCK` | `false` | `true` skips the network and always uses `data/mock_readings.json`. |
| `MOCK_SCENARIO` | unset | Forces mock data for one scenario: `good`, `satisfactory`, `moderate`, `poor`, `very_poor`, `severe`, `spike`. |
| `MONITOR_CITY` | `Lahore` | City to watch: Lahore, Karachi, Islamabad, Rawalpindi, Faisalabad, Multan, Peshawar, Quetta, Gujranwala, Sialkot. |
| `LIVE_CACHE_MINUTES` | `10` | Reuse a city's live data this long before asking Open-Meteo again (it updates hourly). `0` = no cache. |
| `FORECAST_CACHE_MINUTES` | `30` | Reuse a city's live forecast this long before asking Open-Meteo again. `0` = no cache. The forecast follows the same `USE_MOCK`, `MOCK_SCENARIO` and dashboard scenario switch as the monitor. |

### Alerts

| Variable | Default | What it does |
|----------|---------|--------------|
| `ALERT_COOLDOWN_MINUTES` | `30` | After an alert, how long before the same place can alert again for a spike or after recovering. Getting worse always alerts immediately. |
| `ALERT_MEMORY_HOURS` | `3` | Alert memory older than this is forgotten, so a level that stays high alerts again. Memory is also cleared at startup whenever `USE_MOCK` or `MOCK_SCENARIO` forces mock data. |
| `TELEGRAM_BOT_TOKEN` | placeholder | Telegram bot token. A **secret**: put it in `.env` only. Leave the placeholder to use only the dashboard feed. |
| `TELEGRAM_CHAT_ID` | placeholder | The chat or group the bot posts to. |
| `ALERT_SIMULATIONS_TO_TELEGRAM` | `false` | Alerts from mock data are marked `[SIMULATION]` and stay in the dashboard feed. `true` also sends them to Telegram (e.g. to test the bot). |

**Predictive alerts:** when the air is below Unhealthy now but the forecast reaches Unhealthy or worse within 6 hours, the alert agent sends a `warning` (never `critical`) starting with `[FORECAST]`, with kind `forecast`. It uses the same cooldown, memory expiry, `[SIMULATION]` and Telegram rules as other alerts, does not repeat for the same forecast peak, and stays quiet when a current-conditions alert already covers that level. Alerts stored before `kind` existed read as `current`.

**Telegram setup:** in Telegram, talk to @BotFather, send `/newbot`, and copy the token. Add the bot to your group and send a message there, then open `https://api.telegram.org/bot<token>/getUpdates` and copy `"chat":{"id": ...}`. Messages are sent in the background with a 3 s timeout; if one fails, the alert stays in the feed marked `failed: telegram: ...` and a warning is logged. The token is never written to logs.

## Demo tips

- **Switch scenarios from the dashboard's "Demo scenario" menu.** It takes effect on the next poll, clears the alert memory so the new scenario alerts at once, and "Live data" switches back. Nothing to restart.
- **Force a smog emergency:** pick `severe` (or set `MOCK_SCENARIO=severe` in `.env` and restart). Use `spike` to show air building from clean to severe and back, about one step every 5 seconds, with a "Sudden spike" badge and escalating alerts (info → warning → critical).
- **Mock data is always labelled:** the dashboard shows a SIMULATED DATA banner, and every alert from mock data starts with `[SIMULATION]` and is not sent to Telegram unless you allow it.
- **Rehearsals don't swallow the demo alert:** restarting with mock data forced, or switching scenario in the menu, clears the alert memory. To also start with an empty feed, stop the server and delete `var/alerts.json`.
- **Show a predictive alert:** pick `moderate`. Its scripted forecast climbs to Unhealthy within a few hours, so a `[FORECAST]` warning arrives before conditions get there. `spike` and the high scenarios show forecasts that improve.
- **The forecast is a model estimate**, not a measurement: hourly CAMS model output from Open-Meteo, with confidence high for 0–6 h, medium for 6–24 h, low beyond. Mock forecasts are labelled as simulated.
- **The AQI is an estimate** from the latest hourly PM2.5 (the dashboard says so). Official US AQI uses longer averages, so other sites may show different numbers.

## Data attribution

Air quality data from [Open-Meteo](https://open-meteo.com) (free, no key, non-commercial use), based on CAMS ENSEMBLE data from the Copernicus Atmosphere Monitoring Service. If a live call fails or takes more than 10 s, the monitor falls back to mock data. The forecast uses the same API's hourly `pm2_5` and `pm10` forecast (`forecast_days=4`) and falls back to the scripted mock forecast the same way.

## Adding an agent

1. Create `agents/<name>.py` with `def run(state: SmogState) -> dict:` that returns only the keys it owns.
2. Add its output type and state key in `schemas.py`.
3. Add a node and edge in `graph.py`.
