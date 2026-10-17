"""Monitor agent: collects and cleans air quality readings. It does NOT judge severity.

Owns: state["readings"]

Live data: Open-Meteo Air Quality API (free, no API key, non-commercial use).
    Air quality data from Open-Meteo (https://open-meteo.com), based on
    CAMS ENSEMBLE data from the Copernicus Atmosphere Monitoring Service.
Mock data: data/mock_readings.json. Used when
    - USE_MOCK=true, or MOCK_SCENARIO is set (picking a scenario means "give me mock"), or
    - the live call fails or times out, so the demo never dies on stage.

Env vars:
    MONITOR_CITY   city to watch (default Lahore, see CITIES)
    USE_MOCK       true -> skip the network, use mock data
    MOCK_SCENARIO  good | moderate | unhealthy_sensitive | unhealthy |
                   very_unhealthy | hazardous | spike

Try it: python agents/monitor.py [City]
"""
import json
import logging
import math
import os
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

if __package__ in (None, ""):  # run as a script: make `schemas` importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schemas import Reading, SmogState  # noqa: E402

log = logging.getLogger(__name__)

API_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
TIMEOUT_SECONDS = 10
MOCK_FILE = Path(__file__).parent.parent / "data" / "mock_readings.json"
MOCK_STEP_SECONDS = 5   # mock "hour" advances every N real seconds; lower = faster demo
WINDOW = 6              # how many recent readings to hand to analysis
DEFAULT_CITY = "Lahore"
MICROGRAMS = {"μg/m³", "µg/m³"}  # Open-Meteo uses Greek mu, our docs use the micro sign

# City -> (latitude, longitude) of the city centre
CITIES: dict[str, tuple[float, float]] = {
    "Lahore": (31.55, 74.34),
    "Karachi": (24.86, 67.01),
    "Islamabad": (33.68, 73.05),
    "Rawalpindi": (33.57, 73.02),
    "Faisalabad": (31.45, 73.14),
    "Multan": (30.16, 71.52),
    "Peshawar": (34.02, 71.52),
    "Quetta": (30.18, 66.98),
    "Gujranwala": (32.19, 74.19),
    "Sialkot": (32.49, 74.52),
}

# ponytail: in-memory history per city, lost on restart. Use a DB if you need real history.
_history: dict[str, deque[Reading]] = {}


# ---------- graph entry point ----------

def run(state: SmogState) -> dict:
    """Graph node: recent readings for MONITOR_CITY, oldest first."""
    city = _canonical_city(os.getenv("MONITOR_CITY", DEFAULT_CITY))
    if _mock_requested():
        return {"readings": mock_readings(city)}
    try:
        reading = _fetch_live(city)
    except Exception as e:  # network/API/data errors -> keep the demo alive
        log.warning("Live data failed for %s, using mock: %s", city, e)
        return {"readings": mock_readings(city)}

    history = _history.setdefault(city, deque(maxlen=WINDOW))
    # Open-Meteo updates hourly, so repeated polls return the same hour: replace, don't duplicate
    if history and history[-1]["timestamp"] == reading["timestamp"]:
        history[-1] = reading
    else:
        history.append(reading)
    return {"readings": list(history)}


# ---------- public helpers ----------

def fetch_air_quality(
    city: str, lat: float | None = None, lon: float | None = None, scenario: str | None = None
) -> Reading:
    """Latest clean reading for a city. Never raises: falls back to mock data.

    lat/lon are optional for cities in CITIES. Passing a scenario forces mock data.
    """
    city = _canonical_city(city)
    if scenario or _mock_requested():
        return mock_readings(city, scenario)[-1]
    try:
        return _fetch_live(city, lat, lon)
    except Exception as e:
        log.warning("Live data failed for %s, using mock: %s", city, e)
        return mock_readings(city, scenario)[-1]


def city_coordinates(city: str) -> tuple[float, float]:
    """(lat, lon) for a known city, case-insensitive. Raises ValueError if unknown."""
    name = _canonical_city(city)
    if name not in CITIES:
        raise ValueError(f"Unknown city {city!r}. Pass lat/lon or add it to CITIES: {', '.join(CITIES)}")
    return CITIES[name]


def mock_readings(city: str = DEFAULT_CITY, scenario: str | None = None, window: int = WINDOW) -> list[Reading]:
    """The last `window` mock readings for a scenario, oldest first, sliding forward with the clock."""
    data = json.loads(MOCK_FILE.read_text(encoding="utf-8"))
    name = _pick_scenario(data, city, scenario)
    series = data["scenarios"][name]
    now_index = int(time.time() // MOCK_STEP_SECONDS)
    this_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    readings: list[Reading] = []
    for back in range(window - 1, -1, -1):  # oldest first
        i = (now_index - back) % len(series["pm25"])
        readings.append({
            "location": city,
            "timestamp": (this_hour - timedelta(hours=back)).isoformat(),
            "pm25": _clean_value(series["pm25"][i]) or 0.0,
            "pm10": _clean_value(series["pm10"][i]),
            "source": "mock",
        })
    return readings


# ---------- internals ----------

def _fetch_live(city: str, lat: float | None = None, lon: float | None = None) -> Reading:
    """Calls Open-Meteo and returns a cleaned Reading. Raises on any problem."""
    if lat is None or lon is None:
        lat, lon = city_coordinates(city)
    resp = requests.get(
        API_URL,
        params={"latitude": lat, "longitude": lon, "current": "pm2_5,pm10", "timezone": "auto"},
        timeout=TIMEOUT_SECONDS,
    )
    try:
        data = resp.json()
    except ValueError:
        data = {}
    # Errors come back as HTTP 400 with {"error": true, "reason": "..."}
    if not resp.ok or data.get("error"):
        raise RuntimeError(f"Open-Meteo HTTP {resp.status_code}: {data.get('reason') or resp.text[:200]}")
    return _clean_live(city, data)


def _clean_live(city: str, data: dict) -> Reading:
    """Turns an Open-Meteo response into a Reading with consistent units and no surprises."""
    current = data.get("current") or {}
    units = data.get("current_units") or {}
    for var in ("pm2_5", "pm10"):
        if var in units and units[var] not in MICROGRAMS:
            raise ValueError(f"unexpected unit for {var}: {units[var]!r}")

    pm25 = _clean_value(current.get("pm2_5"))
    if pm25 is None:  # PM2.5 is required: no value means no usable reading
        raise ValueError("Open-Meteo returned no valid PM2.5 value")
    return {
        "location": city,
        "timestamp": _to_utc_iso(current.get("time"), data.get("utc_offset_seconds") or 0),
        "pm25": pm25,
        "pm10": _clean_value(current.get("pm10")),  # optional in the schema
        "source": "live",
    }


def _clean_value(value) -> float | None:
    """Float rounded to 0.1, or None for missing, non-numeric, NaN or negative values."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or number < 0:
        return None
    return round(number, 1)


def _to_utc_iso(local_time: str | None, utc_offset_seconds: int) -> str:
    """Open-Meteo local time ("2026-10-17T11:00") + offset -> ISO 8601 UTC."""
    if not local_time:
        log.warning("Open-Meteo response has no time, using now")
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    utc = datetime.fromisoformat(local_time) - timedelta(seconds=utc_offset_seconds)
    return utc.replace(tzinfo=timezone.utc).isoformat()


def _mock_requested() -> bool:
    use_mock = os.getenv("USE_MOCK", "").strip().lower() in {"1", "true", "yes"}
    return use_mock or bool(os.getenv("MOCK_SCENARIO", "").strip())


def _pick_scenario(data: dict, city: str, scenario: str | None) -> str:
    """Explicit scenario > MOCK_SCENARIO env > the city's default > the file's default."""
    default = data["city_defaults"].get(city, data["default_scenario"])
    name = (scenario or os.getenv("MOCK_SCENARIO") or default).strip().lower()
    if name not in data["scenarios"]:
        log.warning("Unknown mock scenario %r, using %r. Options: %s", name, default, ", ".join(data["scenarios"]))
        return default
    return name


def _canonical_city(city: str) -> str:
    """"  lahore " -> "Lahore" for known cities; unknown names are just trimmed."""
    city = city.strip()
    return next((name for name in CITIES if name.lower() == city.lower()), city)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:  # pick up USE_MOCK etc. from .env, like app.py does
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    city = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CITY
    print(json.dumps(fetch_air_quality(city), indent=2, ensure_ascii=False))
