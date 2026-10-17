"""Contracts between agents. Change these as a team — every agent depends on them.

Flow: monitor -> analysis -> advisory -> alert
Each agent is a function: (SmogState) -> dict with ONLY the keys it owns.
LangGraph merges that dict back into the shared state.
"""
from typing import Literal, TypedDict

Level = Literal[
    "good", "moderate", "unhealthy_sensitive", "unhealthy", "very_unhealthy", "hazardous"
]


class Reading(TypedDict):
    """One air quality measurement. Owned by: monitor agent."""
    location: str
    timestamp: str          # ISO 8601, UTC
    pm25: float             # µg/m³
    pm10: float | None      # µg/m³, None if the station doesn't report it
    source: Literal["live", "mock"]  # live = Open-Meteo API


class Analysis(TypedDict):
    """Interpretation of the readings. Owned by: analysis agent."""
    aqi: int                # US EPA AQI computed from latest PM2.5
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
    status: str             # "sent", or "failed: <why>" if Telegram failed and only the feed has it


class SmogState(TypedDict, total=False):
    """Everything that flows through the graph. Each key has one owner."""
    readings: list[Reading]       # monitor; oldest first, latest last
    analysis: Analysis            # analysis
    advisory: Advisory            # advisory
    alerts: list[Alert]           # alert; empty list = nothing to alert
