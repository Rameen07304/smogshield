"""Monitor agent: collects and cleans air quality readings. It does NOT judge severity.

Owns: state["readings"]

Live data: Open-Meteo Air Quality API (free, no API key, non-commercial use).
    Air quality data from Open-Meteo (https://open-meteo.com), based on
    CAMS ENSEMBLE data from the Copernicus Atmosphere Monitoring Service.
    One call returns the past hours too, so the trend window is full from the first poll.
Mock data: data/mock_readings.json. Used when
    - USE_MOCK=true, or MOCK_SCENARIO is set (picking a scenario means "give me mock"), or
    - the live call fails or times out, so the demo never dies on stage.

Env vars:
    MONITOR_CITY   city to watch (default Lahore, see CITIES)
    USE_MOCK       true -> skip the network, use mock data
    MOCK_SCENARIO  good | satisfactory | moderate | poor |
                   very_poor | severe | spike
    LIVE_CACHE_MINUTES  reuse a city's live reading this long (default 10, 0 = off).
                   Open-Meteo updates hourly, so the dashboard's 5 s polling doesn't need more.

Try it: python agents/monitor.py [City]
"""
import json
import logging
import math
import os
import sys
import time
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
DEFAULT_CACHE_MINUTES = 10
MICROGRAMS = {"μg/m³", "µg/m³"}  # Open-Meteo uses Greek mu, our docs use the micro sign

# Last resort if data/mock_readings.json is missing or broken: one small, unremarkable series,
# so the pipeline still runs (the dashboard labels it as simulated like any mock data).
BUILTIN_MOCK: dict = {
    "default_scenario": "builtin",
    "city_defaults": {},
    "scenarios": {"builtin": {"pm25": [20, 22, 24, 23, 21, 22], "pm10": [40, 44, 48, 46, 42, 44]}},
}

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
    # Punjab winter smog hotspots (Wikipedia infobox coordinates, checked against OpenStreetMap)
    "Sheikhupura": (31.71, 73.99),
    "Kasur": (31.12, 74.45),
    "Sahiwal": (30.66, 73.11),
    "Sargodha": (32.08, 72.67),
    "Bahawalpur": (29.40, 71.68),
}
# Urdu city names for the Urdu interface and Urdu alert messages
CITIES_UR: dict[str, str] = {
    "Lahore": "لاہور", "Karachi": "کراچی", "Islamabad": "اسلام آباد", "Rawalpindi": "راولپنڈی",
    "Faisalabad": "فیصل آباد", "Multan": "ملتان", "Peshawar": "پشاور", "Quetta": "کوئٹہ",
    "Gujranwala": "گوجرانوالہ", "Sialkot": "سیالکوٹ", "Sheikhupura": "شیخوپورہ", "Kasur": "قصور",
    "Sahiwal": "ساہیوال", "Sargodha": "سرگودھا", "Bahawalpur": "بہاولپور",
}

# (city, lat, lon) -> (time.monotonic() when fetched, window of readings). Only successes are cached.
_live_cache: dict[tuple[str, float, float], tuple[float, list[Reading]]] = {}


# ---------- graph entry point ----------

def run(state: SmogState) -> dict:
    """Graph node: recent readings for MONITOR_CITY, oldest first."""
    city = _canonical_city(os.getenv("MONITOR_CITY", DEFAULT_CITY))
    if _mock_requested():
        return {"readings": mock_readings(city)}
    try:
        return {"readings": _fetch_live_cached(city)}
    except Exception as e:  # network/API/data errors -> keep the demo alive
        log.warning("Live data failed for %s, using mock: %s", city, e)
        return {"readings": mock_readings(city)}


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
        return _fetch_live_cached(city, lat, lon)[-1]
    except Exception as e:
        log.warning("Live data failed for %s, using mock: %s", city, e)
        return mock_readings(city, scenario)[-1]


def city_coordinates(city: str) -> tuple[float, float]:
    """(lat, lon) for a known city, case-insensitive. Raises ValueError if unknown."""
    name = _canonical_city(city)
    if name not in CITIES:
        raise ValueError(f"Unknown city {city!r}. Pass lat/lon or add it to CITIES: {', '.join(CITIES)}")
    return CITIES[name]


def mock_scenarios() -> list[str]:
    """Names of the available mock scenarios (for the dashboard's demo control)."""
    return list(_load_mock_data()["scenarios"])


def city_default_scenario(city: str) -> str:
    """The mock scenario a city shows by default (its own line in city_defaults)."""
    data = _load_mock_data()
    return data["city_defaults"].get(_canonical_city(city), data["default_scenario"])


def mock_readings(city: str = DEFAULT_CITY, scenario: str | None = None, window: int = WINDOW) -> list[Reading]:
    """The last `window` mock readings for a scenario, oldest first, sliding forward with the clock."""
    data = _load_mock_data()
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

def _load_mock_data() -> dict:
    """data/mock_readings.json, checked. Missing, corrupt or malformed -> BUILTIN_MOCK (never raises)."""
    try:
        data = json.loads(MOCK_FILE.read_text(encoding="utf-8"))
        _check_mock_data(data)
        return data
    except (OSError, ValueError, TypeError, AttributeError) as e:
        log.warning("Mock data file %s is unusable (%s), using a built-in reading", MOCK_FILE, e)
        return BUILTIN_MOCK


def _check_mock_data(data: dict) -> None:
    """Raises ValueError unless the mock file has the shape mock_readings() relies on."""
    scenarios = data["scenarios"] if isinstance(data, dict) and isinstance(data.get("scenarios"), dict) else None
    if not scenarios:
        raise ValueError("no scenarios")
    for name, series in scenarios.items():
        pm25, pm10 = series.get("pm25"), series.get("pm10")
        if not isinstance(pm25, list) or not pm25 or not isinstance(pm10, list) or len(pm10) != len(pm25):
            raise ValueError(f"scenario {name!r} needs equal, non-empty pm25 and pm10 lists")
    if data.get("default_scenario") not in scenarios:
        raise ValueError("default_scenario is not one of the scenarios")
    if not isinstance(data.get("city_defaults", {}), dict):
        raise ValueError("city_defaults must be an object")
    data.setdefault("city_defaults", {})


def _fetch_live_cached(city: str, lat: float | None = None, lon: float | None = None) -> list[Reading]:
    """_fetch_live, but reuses a recent success for LIVE_CACHE_MINUTES. Failures are not cached."""
    if lat is None or lon is None:
        lat, lon = city_coordinates(city)
    key = (city, round(lat, 2), round(lon, 2))
    ttl = _cache_seconds()
    now = time.monotonic()
    cached = _live_cache.get(key)
    if not (cached and ttl > 0 and now - cached[0] < ttl):
        cached = (now, _fetch_live(city, lat, lon))
        _live_cache[key] = cached
    return [dict(r) for r in cached[1]]  # copies, so callers can't change the cached window


def _cache_seconds() -> float:
    raw = os.getenv("LIVE_CACHE_MINUTES", "").strip()
    try:
        minutes = float(raw) if raw else DEFAULT_CACHE_MINUTES
        if minutes < 0:
            raise ValueError
    except ValueError:
        log.warning("Bad LIVE_CACHE_MINUTES %r, using %d", raw, DEFAULT_CACHE_MINUTES)
        minutes = DEFAULT_CACHE_MINUTES
    return minutes * 60


PAST_DAYS = 7                    # the "last 7 days" strip on the city list
PAST_DAYS_CACHE_SECONDS = 3600   # past days don't change, so one fetch per city per hour is plenty
_past_days_cache: dict[str, tuple[float, list[dict]]] = {}


def past_days(city: str) -> list[dict] | None:
    """The last 7 full local days, oldest first: [{"date", "pm25", "aqi", "level"}] from the 24-hour average
    PM2.5 (NCAP categories are defined on 24-hour averages). Live data only; None when it can't be fetched."""
    from agents import analysis  # imported here: the monitor needs analysis for nothing else
    if os.getenv("USE_MOCK", "").strip().lower() in {"1", "true", "yes"}:
        return None  # offline mode: no network at all
    cached = _past_days_cache.get(city)
    if cached and time.monotonic() - cached[0] < PAST_DAYS_CACHE_SECONDS:
        return [dict(d) for d in cached[1]]
    try:
        lat, lon = city_coordinates(city)
        resp = requests.get(API_URL, params={"latitude": lat, "longitude": lon, "hourly": "pm2_5",
                                             "past_days": PAST_DAYS, "forecast_days": 1, "timezone": "auto"},
                            timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        days = daily_averages(resp.json())
    except Exception as e:  # the map works without it
        log.warning("Past days unavailable for %s: %s", city, e)
        return None
    result = [{"date": d, "pm25": avg, **dict(zip(("aqi", "level"), analysis.pm25_to_aqi(avg)))} for d, avg in days]
    _past_days_cache[city] = (time.monotonic(), result)
    return [dict(d) for d in result]


def daily_averages(data: dict) -> list[tuple[str, float]]:
    """(local date, average PM2.5) for the last PAST_DAYS days before today, oldest first.
    A day needs 18+ hourly values to count; today (still in progress) never does."""
    hourly = data.get("hourly") or {}
    days: dict[str, list[float]] = {}
    for local_time, pm25 in zip(hourly.get("time") or [], hourly.get("pm2_5") or []):
        if isinstance(pm25, (int, float)) and not isinstance(pm25, bool) and pm25 >= 0:
            days.setdefault(local_time[:10], []).append(pm25)
    today = max(days, default="")
    full = [d for d in sorted(days) if d != today and len(days[d]) >= 18][-PAST_DAYS:]
    return [(d, round(sum(days[d]) / len(days[d]), 1)) for d in full]


def _fetch_live(city: str, lat: float | None = None, lon: float | None = None) -> list[Reading]:
    """Calls Open-Meteo and returns the recent window of clean Readings, oldest first. Raises on any problem."""
    if lat is None or lon is None:
        lat, lon = city_coordinates(city)
    resp = requests.get(
        API_URL,
        params={
            "latitude": lat, "longitude": lon,
            "hourly": "pm2_5,pm10",
            "past_hours": WINDOW,   # the past 6 hours...
            "forecast_hours": 1,    # ...plus the current hour, and nothing in the future
            "timezone": "auto",
        },
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


def _clean_live(city: str, data: dict) -> list[Reading]:
    """Turns Open-Meteo's hourly arrays into clean Readings: UTC, oldest first, at most WINDOW."""
    hourly = data.get("hourly") or {}
    units = data.get("hourly_units") or {}
    for var in ("pm2_5", "pm10"):
        if var in units and units[var] not in MICROGRAMS:
            raise ValueError(f"unexpected unit for {var}: {units[var]!r}")

    times = hourly.get("time") or []
    pm25s, pm10s = hourly.get("pm2_5") or [], hourly.get("pm10") or []
    offset = data.get("utc_offset_seconds") or 0
    readings: list[Reading] = []
    for i, local_time in enumerate(times):
        pm25 = _clean_value(pm25s[i] if i < len(pm25s) else None)
        if pm25 is None or not local_time:  # PM2.5 is required: skip hours without it
            continue
        try:
            timestamp = _to_utc_iso(local_time, offset)
        except ValueError:
            continue
        readings.append({
            "location": city,
            "timestamp": timestamp,
            "pm25": pm25,
            "pm10": _clean_value(pm10s[i] if i < len(pm10s) else None),  # optional in the schema
            "source": "live",
        })
    if not readings:
        raise ValueError("Open-Meteo returned no valid hourly PM2.5 values")
    if len(readings) < len(times):
        log.info("Skipped %d hour(s) without valid PM2.5 for %s", len(times) - len(readings), city)
    readings.sort(key=lambda r: r["timestamp"])  # same UTC format, so text order = time order
    return readings[-WINDOW:]


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
