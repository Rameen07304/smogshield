"""Alert agent: decides whether to raise an alert, and how loud.

Reads: state["analysis"], state["advisory"], state["readings"]
Owns:  state["alerts"]
Alerts are shown in the dashboard. Add Telegram/SMS/email sending here later.
"""
from datetime import datetime, timezone

from schemas import Alert, SmogState


def run(state: SmogState) -> dict:
    analysis, advisory = state["analysis"], state["advisory"]
    location = state["readings"][-1]["location"]

    if analysis["level"] in ("very_unhealthy", "hazardous"):
        severity = "critical"
    elif analysis["is_hazardous"]:
        severity = "warning"
    elif analysis["level"] == "unhealthy_sensitive" and analysis["trend"] == "rising":
        severity = "info"  # early heads-up before it gets bad
    else:
        return {"alerts": []}

    alert: Alert = {
        "severity": severity,
        "message": f"{location}: AQI {analysis['aqi']}. {advisory['headline']}",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return {"alerts": [alert]}
