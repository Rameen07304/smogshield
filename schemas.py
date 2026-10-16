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
    source: Literal["openaq", "mock"]


class Analysis(TypedDict):
    """Interpretation of the readings. Owned by: analysis agent."""
    aqi: int                # US EPA AQI computed from latest PM2.5
    level: Level
    trend: Literal["rising", "falling", "stable"]
    is_hazardous: bool      # True from "unhealthy" upward


class Advisory(TypedDict):
    """Guidance for the public. Owned by: advisory agent."""
    headline: str
    actions: list[str]


class Alert(TypedDict):
    """A notification shown in the dashboard. Owned by: alert agent."""
    severity: Literal["info", "warning", "critical"]
    message: str
    created_at: str         # ISO 8601, UTC


class SmogState(TypedDict, total=False):
    """Everything that flows through the graph. Each key has one owner."""
    readings: list[Reading]       # monitor; oldest first, latest last
    analysis: Analysis            # analysis
    advisory: Advisory            # advisory
    alerts: list[Alert]           # alert; empty list = nothing to alert
