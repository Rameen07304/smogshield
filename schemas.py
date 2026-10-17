"""Contracts between agents. Change these as a team — every agent depends on them.

Flow: monitor -> forecast -> analysis -> advisory -> alert
Each agent is a function: (SmogState) -> dict with ONLY the keys it owns.
LangGraph merges that dict back into the shared state.
"""
from typing import Literal, TypedDict

Level = Literal[
    "good", "moderate", "unhealthy_sensitive", "unhealthy", "very_unhealthy", "hazardous",
    "unknown",  # no valid readings: never treat as good
]


class Reading(TypedDict):
    """One air quality measurement. Owned by: monitor agent."""
    location: str
    timestamp: str          # ISO 8601, UTC
    pm25: float             # µg/m³
    pm10: float | None      # µg/m³, None if the station doesn't report it
    source: Literal["live", "mock"]  # live = Open-Meteo API


Confidence = Literal["high", "medium", "low"]   # forecast: high 0-6 h ahead, medium 6-24 h, low beyond
ForecastTrend = Literal["improving", "worsening", "stable"]


class ForecastPoint(TypedDict):
    """One forecast hour. Owned by: forecast agent."""
    time: str               # ISO 8601, UTC, start of the hour
    hours_ahead: int        # 0 = the current hour
    pm25: float             # µg/m³, model estimate
    aqi: int                # same pm25_to_aqi as the current reading, so the two compare
    level: Level
    confidence: Confidence


class ForecastWindow(TypedDict):
    """Summary of the next N hours. Owned by: forecast agent."""
    hours: int              # 6 or 24
    peak_aqi: int
    peak_time: str          # ISO 8601, UTC
    peak_level: Level
    typical_level: Level    # level of the window's average PM2.5
    trend: ForecastTrend
    confidence: Confidence


class BestTime(TypedDict):
    """Lowest-PM2.5 ~2-hour window in the next 24 hours. Owned by: forecast agent."""
    start: str              # ISO 8601, UTC
    end: str                # ISO 8601, UTC (exclusive)
    avg_pm25: float
    aqi: int
    level: Level


class DayOutlook(TypedDict):
    """One day of the multi-day outlook. Owned by: forecast agent."""
    date: str               # local calendar date in the city, YYYY-MM-DD
    peak_aqi: int
    peak_level: Level
    confidence: Confidence


class Forecast(TypedDict):
    """Short-term forecast for the monitored city. Owned by: forecast agent."""
    location: str
    generated_at: str       # ISO 8601, UTC
    source: Literal["live", "mock"]
    is_model_estimate: bool # always True: a forecast is a model estimate, never a measurement
    note: str               # one line saying where the forecast comes from
    hourly: list[ForecastPoint]          # the next 24 hours, oldest first
    next_6h: ForecastWindow | None       # None only when there is no forecast data at all
    next_24h: ForecastWindow | None
    best_time: BestTime | None
    outlook: list[DayOutlook]            # one entry per local day, today first


class Analysis(TypedDict):
    """Interpretation of the readings. Owned by: analysis agent."""
    aqi: int | None         # US EPA AQI computed from latest PM2.5; None when level is "unknown"
    level: Level            # the AQI category
    trend: Literal["rising", "falling", "stable"]
    trend_per_hour: float   # PM2.5 change in µg/m³ per hour over the window (+ rising, - falling)
    is_hazardous: bool      # True from "unhealthy" upward
    is_spike: bool          # sudden jump vs the recent window, even if the level is still low
    reason: str             # one-line, human-readable explanation of the above


Audience = Literal["general", "children", "elderly", "respiratory_heart"]


class UrduAdvisory(TypedDict):
    """Urdu version of the public advice. Owned by: advisory agent."""
    headline: str
    actions: list[str]


class Advisory(TypedDict):
    """Guidance for the public. Owned by: advisory agent."""
    headline: str
    actions: list[str]                      # general public, time_note first if any (the dashboard shows this)
    audiences: dict[Audience, list[str]]    # advice per audience; children includes schools
    time_note: str                          # trend/spike context, "" if none
    disclaimer: str                         # "general guidance, not medical advice"
    urdu: UrduAdvisory


class Alert(TypedDict):
    """A notification shown in the dashboard. Owned by: alert agent."""
    severity: Literal["info", "warning", "critical"]
    message: str
    created_at: str         # ISO 8601, UTC
    location: str
    level: Level            # analysis level that triggered the alert
    channel: Literal["feed", "telegram"]  # where it was delivered (the feed always gets a copy)
    status: str             # "sent"; "queued" while Telegram sends in the background;
                            # "failed: <why>" if Telegram failed and only the feed has it


class SmogState(TypedDict, total=False):
    """Everything that flows through the graph. Each key has one owner."""
    readings: list[Reading]       # monitor; oldest first, latest last
    forecast: Forecast            # forecast
    analysis: Analysis            # analysis
    advisory: Advisory            # advisory
    alerts: list[Alert]           # alert; empty list = nothing to alert
