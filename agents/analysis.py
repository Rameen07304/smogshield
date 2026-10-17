"""Analysis agent: turns raw readings into AQI, level, trend and a spike flag.

Reads: state["readings"]  (oldest first, about 6 hourly readings)
Owns:  state["analysis"]
Pure rules, no network: the same readings always give the same analysis. Never raises.
"""
import logging
import math
from datetime import datetime, timezone

from schemas import Analysis, Level, Reading, SmogState

log = logging.getLogger(__name__)

# US EPA PM2.5 breakpoints (2024 revision): (conc_low, conc_high, aqi_low, aqi_high, level)
PM25_BREAKPOINTS: list[tuple[float, float, int, int, Level]] = [
    (0.0, 9.0, 0, 50, "good"),
    (9.1, 35.4, 51, 100, "moderate"),
    (35.5, 55.4, 101, 150, "unhealthy_sensitive"),
    (55.5, 125.4, 151, 200, "unhealthy"),
    (125.5, 225.4, 201, 300, "very_unhealthy"),
    (225.5, 325.4, 301, 500, "hazardous"),
]
HAZARDOUS_LEVELS = {"unhealthy", "very_unhealthy", "hazardous"}
LEVEL_LABELS: dict[str, str] = {
    "good": "Good",
    "moderate": "Moderate",
    "unhealthy_sensitive": "Unhealthy for sensitive groups",
    "unhealthy": "Unhealthy",
    "very_unhealthy": "Very unhealthy",
    "hazardous": "Hazardous",
    "unknown": "Data unavailable",
}

# Trend = least-squares slope of PM2.5 over the window. It counts as rising/falling only if
TREND_MIN_RELATIVE = 0.02   # it changes by more than 2% of the window average per hour (~10% over 5 h)
TREND_MIN_ABSOLUTE = 0.5    # and by at least 0.5 µg/m³ per hour (ignores noise in clean air)

# Spike = the latest reading jumps well above the average of the readings before it
SPIKE_MIN_RATIO = 1.5       # at least 50% above the recent average
SPIKE_MIN_JUMP = 15.0       # and at least 15 µg/m³ higher (so 4 -> 7 in clean air is not a spike)


def pm25_to_aqi(pm25: float) -> tuple[int, Level]:
    """US AQI and level for a PM2.5 concentration (µg/m³). Above the top band -> 500."""
    pm25 = max(pm25, 0.0)
    pm25 = int(pm25 * 10) / 10  # EPA truncates to 1 decimal
    for c_lo, c_hi, a_lo, a_hi, level in PM25_BREAKPOINTS:
        if pm25 <= c_hi:
            return round((a_hi - a_lo) / (c_hi - c_lo) * (pm25 - c_lo) + a_lo), level
    return 500, "hazardous"  # off the chart


def run(state: SmogState) -> dict:
    """Graph node: analysis of the latest reading plus the recent window."""
    readings = _valid_readings(state.get("readings") or [])
    if not readings:
        # Should not happen (monitor always falls back to mock), but never crash the pipeline
        log.warning("No valid readings to analyse, returning level 'unknown'")
        return {"analysis": _no_data_analysis()}
    return {"analysis": assess(readings)}


def assess(readings: list[Reading]) -> Analysis:
    """Full assessment of a non-empty window of valid readings, oldest first."""
    values = [r["pm25"] for r in readings]
    latest = values[-1]
    aqi, level = pm25_to_aqi(latest)
    rate = trend_per_hour(readings)
    trend = _classify_trend(rate, sum(values) / len(values))
    spike = is_spike(values)

    reason = f"PM2.5 {latest:g} µg/m³ gives AQI {aqi} ({LEVEL_LABELS[level]})"
    if len(values) < 2:
        reason += "; only 1 reading, so no trend yet"
    else:
        reason += f"; {trend} at {rate:+.1f} µg/m³/h over the last {len(values)} readings"
    if spike:
        reason += f"; sudden spike, {latest - _mean(values[:-1]):+.0f} µg/m³ vs the recent average"

    return {
        "aqi": aqi,
        "level": level,
        "trend": trend,
        "trend_per_hour": rate,
        "is_hazardous": level in HAZARDOUS_LEVELS,
        "is_spike": spike,
        "reason": reason,
    }


def trend_per_hour(readings: list[Reading]) -> float:
    """Least-squares slope of PM2.5 in µg/m³ per hour. 0.0 for fewer than 2 readings."""
    if len(readings) < 2:
        return 0.0
    hours = _hours_since_first(readings)
    values = [r["pm25"] for r in readings]
    x_mean, y_mean = _mean(hours), _mean(values)
    spread = sum((x - x_mean) ** 2 for x in hours)
    if spread == 0:  # all readings have the same timestamp
        return 0.0
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(hours, values)) / spread
    return round(slope, 1)


def is_spike(values: list[float]) -> bool:
    """True if the latest value jumps well above the average of the values before it."""
    if len(values) < 2:
        return False
    latest, before = values[-1], _mean(values[:-1])
    return latest - before >= SPIKE_MIN_JUMP and latest >= before * SPIKE_MIN_RATIO


# ---------- internals ----------

def _classify_trend(rate: float, average: float) -> str:
    if abs(rate) < TREND_MIN_ABSOLUTE or average <= 0 or abs(rate) / average < TREND_MIN_RELATIVE:
        return "stable"
    return "rising" if rate > 0 else "falling"


def _valid_readings(readings: list) -> list[Reading]:
    """Drops readings without a usable PM2.5 (missing, non-numeric, NaN, negative)."""
    valid = []
    for r in readings:
        try:
            pm25 = float(r["pm25"])
        except (TypeError, ValueError, KeyError):
            continue
        if math.isfinite(pm25) and pm25 >= 0:
            valid.append({**r, "pm25": pm25})
    if len(valid) < len(readings):
        log.warning("Ignored %d reading(s) with no valid PM2.5", len(readings) - len(valid))
    return valid


def _hours_since_first(readings: list[Reading]) -> list[float]:
    """Hours from the first reading. If any timestamp is unreadable, assume hourly readings."""
    try:
        times = [_parse_utc(r["timestamp"]) for r in readings]
    except (KeyError, TypeError, ValueError):
        log.warning("Unreadable timestamp in window, assuming hourly readings")
        return [float(i) for i in range(len(readings))]
    return [(t - times[0]).total_seconds() / 3600 for t in times]


def _parse_utc(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _no_data_analysis() -> Analysis:
    # "unknown", never "good": no data must not be reported as clean air
    return {
        "aqi": None,
        "level": "unknown",
        "trend": "stable",
        "trend_per_hour": 0.0,
        "is_hazardous": False,
        "is_spike": False,
        "reason": "No valid readings received, so air quality is unknown.",
    }
