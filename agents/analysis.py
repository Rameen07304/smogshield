"""Analysis agent: turns raw readings into AQI, level and trend.

Reads: state["readings"]
Owns:  state["analysis"]
"""
from schemas import Analysis, Level, SmogState

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
TREND_THRESHOLD = 0.10  # >10% change over the window counts as rising/falling


def pm25_to_aqi(pm25: float) -> tuple[int, Level]:
    pm25 = int(pm25 * 10) / 10  # EPA truncates to 1 decimal
    for c_lo, c_hi, a_lo, a_hi, level in PM25_BREAKPOINTS:
        if pm25 <= c_hi:
            return round((a_hi - a_lo) / (c_hi - c_lo) * (pm25 - c_lo) + a_lo), level
    return 500, "hazardous"  # off the chart


def run(state: SmogState) -> dict:
    readings = state["readings"]
    aqi, level = pm25_to_aqi(readings[-1]["pm25"])

    first, last = readings[0]["pm25"], readings[-1]["pm25"]
    change = (last - first) / first if first else 0
    trend = "rising" if change > TREND_THRESHOLD else "falling" if change < -TREND_THRESHOLD else "stable"

    analysis: Analysis = {
        "aqi": aqi,
        "level": level,
        "trend": trend,
        "is_hazardous": level in HAZARDOUS_LEVELS,
    }
    return {"analysis": analysis}
