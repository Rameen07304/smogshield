"""Monitor agent: fetches air quality readings.

Owns: state["readings"]
Uses OpenAQ when OPENAQ_API_KEY and OPENAQ_LOCATION_ID are set, otherwise mock data.
If OpenAQ fails, it falls back to mock so the demo never dies on stage.
"""
import json
import os
import time
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from schemas import Reading, SmogState

MOCK_FILE = Path(__file__).parent.parent / "data" / "mock_readings.json"
MOCK_STEP_SECONDS = 5   # mock "hour" advances every N real seconds; lower = faster demo
WINDOW = 6              # how many recent readings to hand to analysis

# ponytail: in-memory history, lost on restart. Use a DB if you need real history.
_history: deque[Reading] = deque(maxlen=WINDOW)


def run(state: SmogState) -> dict:
    key, location_id = os.getenv("OPENAQ_API_KEY"), os.getenv("OPENAQ_LOCATION_ID")
    if key and location_id:
        try:
            _history.append(_fetch_openaq(key, location_id))
            return {"readings": list(_history)}
        except Exception as e:  # network/API errors -> keep the demo alive
            print(f"[monitor] OpenAQ failed, using mock: {e}")
    return {"readings": _mock_readings()}


def _get(url: str, key: str) -> dict:
    req = urllib.request.Request(url, headers={"X-API-Key": key})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def _fetch_openaq(key: str, location_id: str) -> Reading:
    base = f"https://api.openaq.org/v3/locations/{location_id}"
    location = _get(base, key)["results"][0]
    # /latest returns values by sensor id, so map sensor id -> parameter name
    params = {s["id"]: s["parameter"]["name"] for s in location["sensors"]}
    latest = {params.get(r["sensorsId"]): r for r in _get(f"{base}/latest", key)["results"]}
    if "pm25" not in latest:
        raise ValueError(f"location {location_id} has no PM2.5 sensor")
    return {
        "location": location["name"],
        "timestamp": latest["pm25"]["datetime"]["utc"],
        "pm25": float(latest["pm25"]["value"]),
        "pm10": float(latest["pm10"]["value"]) if "pm10" in latest else None,
        "source": "openaq",
    }


def _mock_readings() -> list[Reading]:
    """Returns the last WINDOW mock values, sliding forward with the clock."""
    data = json.loads(MOCK_FILE.read_text(encoding="utf-8"))
    values = data["pm25"]
    now_index = int(time.time() // MOCK_STEP_SECONDS)
    now = datetime.now(timezone.utc)
    readings = []
    for back in range(WINDOW - 1, -1, -1):  # oldest first
        readings.append({
            "location": data["location"],
            "timestamp": (now - timedelta(hours=back)).isoformat(timespec="seconds"),
            "pm25": float(values[(now_index - back) % len(values)]),
            "pm10": None,
            "source": "mock",
        })
    return readings
