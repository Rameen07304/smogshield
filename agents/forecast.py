"""Forecast agent: short-term air quality forecast for the monitored city.

Reads: state["readings"] (for the city, and later to anchor mock forecasts)
Owns:  state["forecast"]

Live: Open-Meteo hourly PM2.5 for 4 days (CAMS-based model estimates, not measurements).
The series is cleaned (UTC, rounded to 0.1, nulls and negatives dropped, oldest first) and
cached per city for FORECAST_CACHE_MINUTES (default 30). AQI uses the same pm25_to_aqi as the
current reading, so forecast and current AQI compare directly. Never raises.
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests

from agents import analysis, monitor
from schemas import BestTime, Confidence, DayOutlook, Forecast, ForecastPoint, ForecastWindow, SmogState

log = logging.getLogger(__name__)

FORECAST_DAYS = 4            # today (from 00:00 local, incl. past hours) + 3 more days
HOURS_AHEAD = 24             # length of the hourly forecast handed to the other agents
TIMEOUT_SECONDS = 10
DEFAULT_CACHE_MINUTES = 30   # override with FORECAST_CACHE_MINUTES; 0 = no cache
BEST_TIME_HOURS = 2          # "best time to go outside" window length
# A window's trend compares its first two hours with its last two: it counts as worsening or
# improving only if PM2.5 moves by more than both of these, otherwise it is stable.
TREND_MIN_CHANGE = 0.10      # 10% of the starting level...
TREND_MIN_ABSOLUTE = 3.0     # ...and at least 3 µg/m³ (so 4 -> 6 in clean air is still "stable")
NOTE = "Model forecast from Open-Meteo, based on CAMS (Copernicus Atmosphere Monitoring Service). An estimate, not a measurement."

# (city, lat, lon) -> (time.monotonic() when fetched, cleaned series). Only successes are cached.
_cache: dict[tuple[str, float, float], tuple[float, dict]] = {}


# ---------- graph entry point ----------

def run(state: SmogState) -> dict:
    """Graph node: the forecast for the city the monitor just read."""
    return {"forecast": build_forecast(_city_of(state.get("readings")))}


def build_forecast(city: str, now: datetime | None = None) -> Forecast:
    """Forecast for a city. Never raises: on any failure, a forecast with no data and a reason."""
    now = now or datetime.now(timezone.utc)
    try:
        series = fetch_series(city)
    except Exception as e:  # network/API/data errors: never crash the pipeline
        log.warning("Live forecast failed for %s: %s", city, e)
        return _empty_forecast(city, "mock", now)
    return _forecast_from_series(city, series, "live", now)


# ---------- fetch + clean ----------

def fetch_series(city: str, lat: float | None = None, lon: float | None = None) -> dict:
    """Cleaned hourly series {"offset": utc_offset_seconds, "points": [{"time", "pm25"}]}, cached."""
    if lat is None or lon is None:
        lat, lon = monitor.city_coordinates(city)
    key = (city, round(lat, 2), round(lon, 2))
    ttl = _cache_seconds()
    now = time.monotonic()
    cached = _cache.get(key)
    if not (cached and ttl > 0 and now - cached[0] < ttl):
        cached = (now, _fetch_live(lat, lon))
        _cache[key] = cached
    return {"offset": cached[1]["offset"], "points": [dict(p) for p in cached[1]["points"]]}


def _fetch_live(lat: float, lon: float) -> dict:
    resp = requests.get(
        monitor.API_URL,
        params={
            "latitude": lat, "longitude": lon,
            "hourly": "pm2_5,pm10",
            "forecast_days": FORECAST_DAYS,
            "timezone": "auto",
            "timeformat": "iso8601",
        },
        timeout=TIMEOUT_SECONDS,
    )
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not resp.ok or data.get("error"):
        raise RuntimeError(f"Open-Meteo HTTP {resp.status_code}: {data.get('reason') or resp.text[:200]}")
    return clean_series(data)


def clean_series(data: dict) -> dict:
    """Open-Meteo hourly arrays -> UTC points with valid PM2.5, oldest first. Raises if none."""
    hourly = data.get("hourly") or {}
    unit = (data.get("hourly_units") or {}).get("pm2_5")
    if unit is not None and unit not in monitor.MICROGRAMS:
        raise ValueError(f"unexpected unit for pm2_5: {unit!r}")
    offset = data.get("utc_offset_seconds") or 0
    times, values = hourly.get("time") or [], hourly.get("pm2_5") or []
    points = []
    for i, local_time in enumerate(times):
        pm25 = monitor._clean_value(values[i] if i < len(values) else None)  # None for null/NaN/negative
        if pm25 is None or not local_time:
            continue
        try:
            points.append({"time": monitor._to_utc_iso(local_time, offset), "pm25": pm25})
        except ValueError:
            continue
    if not points:
        raise ValueError("Open-Meteo returned no valid hourly PM2.5 forecast")
    if len(points) < len(times):
        log.info("Forecast: skipped %d hour(s) without valid PM2.5", len(times) - len(points))
    points.sort(key=lambda p: p["time"])  # same UTC format, so text order = time order
    return {"offset": offset, "points": points}


# ---------- build ----------

def confidence_for(hours_ahead: float) -> Confidence:
    """high for 0-6 h ahead, medium for 6-24 h, low beyond 24 h."""
    if hours_ahead <= 6:
        return "high"
    if hours_ahead <= 24:
        return "medium"
    return "low"


def hourly_points(points: list[dict], now: datetime, hours: int = HOURS_AHEAD) -> list[ForecastPoint]:
    """The forecast from the current hour (hours_ahead 0) for the next `hours` hours."""
    start = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    out: list[ForecastPoint] = []
    for p in points:
        ahead = (datetime.fromisoformat(p["time"]) - start).total_seconds() / 3600
        if 0 <= ahead < hours:
            aqi, level = analysis.pm25_to_aqi(p["pm25"])
            out.append({
                "time": p["time"],
                "hours_ahead": int(ahead),
                "pm25": p["pm25"],
                "aqi": aqi,
                "level": level,
                "confidence": confidence_for(ahead),
            })
    return out


def summarize_window(points: list[ForecastPoint], hours: int) -> ForecastWindow | None:
    """Peak, typical level and trend of the first `hours` hours. None when there are no points."""
    window = [p for p in points if p["hours_ahead"] < hours]
    if not window:
        return None
    peak = max(window, key=lambda p: p["aqi"])            # max() keeps the earliest of equal peaks
    average = sum(p["pm25"] for p in window) / len(window)
    return {
        "hours": hours,
        "peak_aqi": peak["aqi"],
        "peak_time": peak["time"],
        "peak_level": peak["level"],
        "typical_level": analysis.pm25_to_aqi(average)[1],
        "trend": _trend([p["pm25"] for p in window]),
        "confidence": confidence_for(hours),
    }


def best_time(points: list[ForecastPoint], span: int = BEST_TIME_HOURS) -> BestTime | None:
    """The `span` consecutive hours with the lowest average PM2.5 (earliest wins a tie)."""
    best: BestTime | None = None
    for i in range(len(points) - span + 1):
        chunk = points[i:i + span]
        if chunk[-1]["hours_ahead"] - chunk[0]["hours_ahead"] != span - 1:
            continue                                       # a gap in the data: not a real window
        average = round(sum(p["pm25"] for p in chunk) / span, 1)
        if best is None or average < best["avg_pm25"]:
            aqi, level = analysis.pm25_to_aqi(average)
            end = datetime.fromisoformat(chunk[-1]["time"]) + timedelta(hours=1)
            best = {"start": chunk[0]["time"], "end": end.isoformat(), "avg_pm25": average, "aqi": aqi, "level": level}
    return best


def daily_outlook(points: list[dict], offset: int, now: datetime) -> list[DayOutlook]:
    """One peak per local calendar day, from the current hour on (rest of today first)."""
    start = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    days: dict[str, dict] = {}
    for p in points:
        when = datetime.fromisoformat(p["time"])
        if when < start:
            continue
        local_date = (when + timedelta(seconds=offset)).date().isoformat()
        if local_date not in days or p["pm25"] > days[local_date]["pm25"]:
            days[local_date] = {"pm25": p["pm25"], "ahead": (when - start).total_seconds() / 3600}
    outlook: list[DayOutlook] = []
    for local_date in sorted(days):
        aqi, level = analysis.pm25_to_aqi(days[local_date]["pm25"])
        outlook.append({"date": local_date, "peak_aqi": aqi, "peak_level": level,
                        "confidence": confidence_for(days[local_date]["ahead"])})
    return outlook


def _trend(values: list[float]) -> str:
    """improving / worsening / stable: the first two hours against the last two."""
    if len(values) < 2:
        return "stable"
    head = sum(values[:2]) / len(values[:2])
    tail = sum(values[-2:]) / len(values[-2:])
    threshold = max(TREND_MIN_ABSOLUTE, head * TREND_MIN_CHANGE)
    if tail - head > threshold:
        return "worsening"
    if head - tail > threshold:
        return "improving"
    return "stable"


def _forecast_from_series(city: str, series: dict, source: str, now: datetime) -> Forecast:
    hourly = hourly_points(series["points"], now)
    return {
        "location": city,
        "generated_at": now.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        "source": source,
        "is_model_estimate": True,
        "note": NOTE,
        "hourly": hourly,
        "next_6h": summarize_window(hourly, 6),
        "next_24h": summarize_window(hourly, HOURS_AHEAD),
        "best_time": best_time(hourly),
        "outlook": daily_outlook(series["points"], series["offset"], now),
    }


def _empty_forecast(city: str, source: str, now: datetime) -> Forecast:
    return {**_forecast_from_series(city, {"offset": 0, "points": []}, source, now),
            "note": "No forecast available right now."}


def _city_of(readings) -> str:
    try:
        return monitor._canonical_city(str(readings[-1]["location"]))
    except (TypeError, IndexError, KeyError):
        return monitor._canonical_city(os.getenv("MONITOR_CITY", monitor.DEFAULT_CITY))


def _cache_seconds() -> float:
    raw = os.getenv("FORECAST_CACHE_MINUTES", "").strip()
    try:
        minutes = float(raw) if raw else DEFAULT_CACHE_MINUTES
        if minutes < 0:
            raise ValueError
    except ValueError:
        log.warning("Bad FORECAST_CACHE_MINUTES %r, using %d", raw, DEFAULT_CACHE_MINUTES)
        minutes = DEFAULT_CACHE_MINUTES
    return minutes * 60
