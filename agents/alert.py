"""Alert agent: decides whether to raise an alert, how urgent it is, and delivers it.

Reads: state["analysis"], state["advisory"], state["readings"], state["forecast"]
Owns:  state["alerts"]  (alerts raised by THIS run; [] = nothing new)

When to alert (per location, so we never spam):
  - the level reaches "moderate" or rises above the last alerted level
    -> alert right away (escalations are never held back by the cooldown)
  - the spike flag is set -> alert, at most once per cooldown
  - same or lower level -> no alert. After a full cooldown without alerts the remembered
    level drops to the current one, so a later rise alerts again but flapping doesn't.
  - memory older than ALERT_MEMORY_HOURS (default 3) is forgotten, so a level that stays
    high gets a fresh alert every few hours instead of never again.

Memory + feed live in var/alerts.json (gitignored). A file, not the graph state, because
the app calls graph.invoke({}) with an empty state on every poll, and a file survives restarts.
When mock data is forced (USE_MOCK / MOCK_SCENARIO), the first run in a new process clears the
memory, so a rehearsal never swallows the demo's alert.

Delivery: every alert goes into the feed (the dashboard reads it). If TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID are set it is also sent to Telegram, in a background thread so the pipeline
never waits for it: the feed entry starts as status "queued" and is updated to "sent", or to
"failed: ..." (channel "feed") with a logged warning. A Telegram failure is never raised.
Alerts based on mock data start with "[SIMULATION]" and are NOT sent to Telegram unless
ALERT_SIMULATIONS_TO_TELEGRAM=true, so a demo can never look like a real emergency.

Predictive (forecast) alerts, kind "forecast": when the air is still below Unhealthy now but the
forecast reaches Unhealthy or worse within the next 6 hours. Always "warning", message starts with
"[FORECAST]" (after "[SIMULATION]" for mock data), same cooldown, memory expiry and Telegram rules,
with their own memory slot per location ("forecast:<location>"). They repeat only when the forecast
peak gets worse, and stay quiet when a current-conditions alert already covered that level.
Every alert carries kind "current" or "forecast"; older stored alerts without it read as "current".
"""
import json
import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from schemas import Alert, SmogState

log = logging.getLogger(__name__)

# urllib3 (used by requests) logs request URLs, and the Telegram URL contains the bot token.
# Silence it completely: above CRITICAL, and never passed up to the root logger, so the token
# can't reach any log at any level, even if someone turns on DEBUG logging.
_urllib3_log = logging.getLogger("urllib3")
_urllib3_log.setLevel(logging.CRITICAL + 1)
_urllib3_log.propagate = False

STORE_FILE = Path(__file__).parent.parent / "var" / "alerts.json"
FEED_SIZE = 100                 # keep the newest N alerts in the feed
DEFAULT_COOLDOWN_MINUTES = 30   # override with ALERT_COOLDOWN_MINUTES
DEFAULT_MEMORY_HOURS = 3        # override with ALERT_MEMORY_HOURS
TELEGRAM_TIMEOUT_SECONDS = 3

# Levels from best to worst; the list index is the severity rank
LEVEL_ORDER = ["good", "satisfactory", "moderate", "poor", "very_poor", "severe"]
THRESHOLD = "moderate"              # lowest level that raises an alert on its own
SIMULATION_PREFIX = "[SIMULATION] "  # on every alert built from mock data
FORECAST_PREFIX = "[FORECAST] "      # on every predictive alert
FORECAST_HORIZON_HOURS = 6           # predictive alerts look this far ahead
FORECAST_TRIGGER = "poor"            # predict only when the forecast reaches this level or worse
FORECAST_SEVERITY = "warning"        # a prediction is never critical
LOCAL_UTC_OFFSET = timedelta(hours=5)   # message times in Pakistan Standard Time, like the advisory
URGENCY = {
    "good": "info",                 # only reachable through a spike
    "satisfactory": "info",         # only reachable through a spike
    "moderate": "info",
    "poor": "warning",
    "very_poor": "critical",
    "severe": "critical",
}
LEVEL_LABELS = {
    "good": "Good", "satisfactory": "Satisfactory", "moderate": "Moderate",
    "poor": "Poor", "very_poor": "Very Poor", "severe": "Severe",
}

_lock = threading.Lock()  # several dashboard tabs can poll at the same time
_startup_done = False     # the first run in each process may clear memory (see module docstring)
# One background worker sends to Telegram in order; Python waits for it at exit, so queued sends finish
_sender = ThreadPoolExecutor(max_workers=1, thread_name_prefix="alert-send")
_pending: list[Future] = []


# ---------- graph entry point ----------

def run(state: SmogState) -> dict:
    """Graph node: new alerts for this reading (usually none)."""
    try:
        return {"alerts": _process(state)}
    except Exception:  # last safety net: alerts must never take the pipeline down
        log.exception("Alert agent failed, no alert this run")
        return {"alerts": []}


# ---------- decision (pure, easy to test) ----------

def should_alert(
    level: str, is_spike: bool, memory: dict | None, now: datetime, cooldown: timedelta,
    max_age: timedelta | None = None,
) -> tuple[bool, dict]:
    """Anti-spam rule for one location. Returns (alert now?, updated memory).

    max_age: forget the memory if the last alert is at least this old (None = never).
    """
    memory = dict(memory or {})
    last_alert = _parse_time(memory.get("alerted_at"))
    if max_age is not None and last_alert is not None and now - last_alert >= max_age:
        memory, last_alert = {}, None  # expired: start fresh, as if never alerted
    last_level = memory.get("level") if memory.get("level") in LEVEL_ORDER else "good"
    last_spike = _parse_time(memory.get("spike_at"))
    rank = LEVEL_ORDER.index(level)

    # After a quiet cooldown, forget the old peak so a later rise alerts again
    quiet = last_alert is None or now - last_alert >= cooldown
    if quiet and rank < LEVEL_ORDER.index(last_level):
        last_level = level

    escalated = rank >= LEVEL_ORDER.index(THRESHOLD) and rank > LEVEL_ORDER.index(last_level)
    new_spike = is_spike and (last_spike is None or now - last_spike >= cooldown)

    memory["level"] = level if escalated else last_level
    if escalated or new_spike:
        memory["alerted_at"] = now.isoformat(timespec="seconds")
    if new_spike:
        memory["spike_at"] = now.isoformat(timespec="seconds")
    return escalated or new_spike, memory


def should_forecast_alert(
    current_level: str, peak_level: str | None, memory: dict | None, current_memory: dict | None,
    now: datetime, cooldown: timedelta, max_age: timedelta | None = None,
) -> tuple[bool, dict]:
    """Anti-spam rule for predictive alerts at one location. Returns (alert now?, updated memory).

    Fires only when the air is below Unhealthy now and the forecast peak is Unhealthy or worse.
    """
    memory = dict(memory or {})
    last_alert = _parse_time(memory.get("alerted_at"))
    if max_age is not None and last_alert is not None and now - last_alert >= max_age:
        memory, last_alert = {}, None                      # expired: as if never alerted
    trigger = LEVEL_ORDER.index(FORECAST_TRIGGER)
    if current_level not in LEVEL_ORDER or peak_level not in LEVEL_ORDER:
        return False, memory
    current, peak = LEVEL_ORDER.index(current_level), LEVEL_ORDER.index(peak_level)

    if not (current < trigger <= peak):
        # Nothing to predict. Once it has been quiet for a full cooldown, forget the old warning,
        # so a new threat later alerts again (and a brief flap in the forecast does not).
        if last_alert is None or now - last_alert >= cooldown:
            memory.pop("level", None)
        return False, memory

    # A current-conditions alert still in memory already warned at this level or worse
    covered = dict(current_memory or {})
    covered_at = _parse_time(covered.get("alerted_at"))
    if (covered.get("level") in LEVEL_ORDER and LEVEL_ORDER.index(covered["level"]) >= peak
            and covered_at is not None and (max_age is None or now - covered_at < max_age)):
        return False, memory

    last = memory.get("level")
    if last in LEVEL_ORDER and peak <= LEVEL_ORDER.index(last):
        return False, memory                                # already predicted this (or worse)
    memory.update(level=peak_level, alerted_at=now.isoformat(timespec="seconds"))
    return True, memory


def urgency_for(level: str) -> str:
    """info / warning / critical for an analysis level (unknown -> warning, to be safe)."""
    return URGENCY.get(level, "warning")


# ---------- delivery ----------

def deliver(alert: Alert, simulated: bool = False) -> Alert:
    """Queues the alert on the external channel if configured, and returns at once.

    The caller writes the returned alert to the feed; the background send updates it later.
    Simulated (mock-data) alerts stay in the feed unless ALERT_SIMULATIONS_TO_TELEGRAM=true.
    """
    channel = _external_channel()
    if channel is not None and simulated and not _simulations_allowed_out():
        log.info("Simulated alert kept in the feed only (set ALERT_SIMULATIONS_TO_TELEGRAM=true to send it)")
        channel = None
    if channel is None:
        return {**alert, "channel": "feed", "status": "sent"}
    name, send = channel
    queued: Alert = {**alert, "channel": name, "status": "queued"}
    try:
        _pending.append(_sender.submit(_send_and_record, name, send, queued))
        _pending[:] = [f for f in _pending if not f.done()]
    except RuntimeError as e:  # executor already shut down (interpreter exiting)
        log.warning("%s delivery not started, alert is in the feed only: %s", name, e)
        return {**alert, "channel": "feed", "status": f"failed: {name}: not started"}
    return queued


def flush(timeout: float | None = None) -> None:
    """Waits for queued sends to finish (tests use this; the app never needs to)."""
    wait(list(_pending), timeout=timeout)


def _send_and_record(name: str, send: Callable[[Alert], None], queued: Alert) -> None:
    """Background job: send, then record the outcome on the feed entry. Never raises."""
    try:
        send(queued)
        outcome = {"channel": name, "status": "sent"}
    except Exception as e:
        reason = _redact(str(e))
        log.warning("%s delivery failed, alert is in the feed only: %s", name, reason)
        outcome = {"channel": "feed", "status": f"failed: {name}: {reason}"[:200]}
    try:
        with _lock:  # also waits until the run that queued us has saved the feed
            store = _load()
            for item in store["feed"]:
                if all(item.get(k) == queued[k] for k in ("created_at", "location", "level", "message")):
                    item.update(outcome)
                    break
            _save(store)
        log.info("ALERT delivery %s", json.dumps({**queued, **outcome}, ensure_ascii=False))
    except Exception:
        log.exception("Could not record %s delivery result", name)


def _external_channel() -> tuple[str, Callable[[Alert], None]] | None:
    """The real channel to try, or None. A channel is a function send(alert) that raises on failure.
    Add SMS/email here the same way."""
    token, chat_id = _telegram_credentials()
    if token and chat_id:
        return "telegram", _send_telegram
    return None


def _simulations_allowed_out() -> bool:
    return os.getenv("ALERT_SIMULATIONS_TO_TELEGRAM", "").strip().lower() in {"1", "true", "yes"}


def _telegram_credentials() -> tuple[str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if token.startswith("your_") or chat_id.startswith("your_"):  # .env.example placeholders
        return "", ""
    return token, chat_id


def _send_telegram(alert: Alert) -> None:
    token, chat_id = _telegram_credentials()
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": f"[{alert['severity'].upper()}] {alert['message']}"},
        timeout=TELEGRAM_TIMEOUT_SECONDS,
    )
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}")  # don't echo the body: keep it short


def _redact(text: str) -> str:
    """Error messages can contain the request URL, which includes the bot token."""
    token, _ = _telegram_credentials()
    return text.replace(token, "***") if token else text


# ---------- feed + memory store (var/alerts.json) ----------

def read_feed(limit: int = 50) -> list[Alert]:
    """Newest alerts first, for the dashboard. Alerts stored before `kind` existed read as "current"
    (the file itself is never rewritten for this)."""
    with _lock:
        return [{**a, "kind": a.get("kind", "current")} for a in _load()["feed"][: max(limit, 0)]]


def reset_memory() -> None:
    """Forget what was alerted (keeps the feed). Used when switching demo scenarios."""
    with _lock:
        store = _load()
        store["memory"] = {}
        _save(store)


def _process(state: SmogState) -> list[Alert]:
    analysis = state.get("analysis") or {}
    advisory = state.get("advisory") or {}
    level = analysis.get("level")
    if level == "unknown":
        log.info("No air quality data, so no alert this run")
        return []
    if level not in LEVEL_ORDER:
        log.warning("Unrecognised or missing level %r, no alert", level)
        return []
    location = _location(state.get("readings"))
    simulated = _is_simulated(state.get("readings"))
    now = datetime.now(timezone.utc)

    with _lock:
        store = _load()
        _clear_memory_on_startup(store)
        alert_now, store["memory"][location] = should_alert(
            level, analysis.get("is_spike") is True, store["memory"].get(location), now,
            _cooldown(), _memory_max_age(),
        )
        alerts: list[Alert] = []
        if alert_now:
            message = _message(location, level, analysis, advisory)
            alerts.append(_record(store, {
                "severity": urgency_for(level),
                "message": SIMULATION_PREFIX + message if simulated else message,
                "created_at": now.isoformat(timespec="seconds"),
                "location": location,
                "level": level,
                "kind": "current",
                "channel": "feed",
                "status": "sent",
            }, simulated))

        # Predictive alert from the forecast (after the current one, so its memory is up to date)
        forecast = state.get("forecast") if isinstance(state.get("forecast"), dict) else {}
        six = forecast.get("next_6h") if isinstance(forecast.get("next_6h"), dict) else {}
        key = f"forecast:{location}"
        predict, store["memory"][key] = should_forecast_alert(
            level, six.get("peak_level"), store["memory"].get(key), store["memory"].get(location),
            now, _cooldown(), _memory_max_age(),
        )
        if predict:
            f_simulated = simulated or forecast.get("source") != "live"
            message = FORECAST_PREFIX + _forecast_message(location, analysis, forecast)
            alerts.append(_record(store, {
                "severity": FORECAST_SEVERITY,
                "message": SIMULATION_PREFIX + message if f_simulated else message,
                "created_at": now.isoformat(timespec="seconds"),
                "location": location,
                "level": six["peak_level"],
                "kind": "forecast",
                "channel": "feed",
                "status": "sent",
            }, f_simulated))
        _save(store)
    return alerts


def _record(store: dict, alert: Alert, simulated: bool) -> Alert:
    """Deliver an alert, log it, and put it at the top of the feed."""
    alert = deliver(alert, simulated)
    log.info("ALERT %s", json.dumps(alert, ensure_ascii=False))
    store["feed"] = [alert, *store["feed"]][:FEED_SIZE]
    return alert


def _forecast_message(location: str, analysis: dict, forecast: dict) -> str:
    """'Lahore: forecast to reach Unhealthy (AQI 172) around 19:00, within 6 hours (now AQI 142). ...'"""
    six = forecast["next_6h"]
    peak = six["peak_level"]
    rank = LEVEL_ORDER.index(peak)
    # when that level is first reached (the time to plan around), not when it peaks
    onset = next((p["time"] for p in forecast.get("hourly") or []
                  if p.get("hours_ahead", 99) < FORECAST_HORIZON_HOURS and p.get("level") in LEVEL_ORDER
                  and LEVEL_ORDER.index(p["level"]) >= rank), six.get("peak_time"))
    try:
        at = (datetime.fromisoformat(onset).astimezone(timezone.utc) + LOCAL_UTC_OFFSET).strftime("%H:%M")
        when = f"around {at}, "
    except (TypeError, ValueError):
        when = ""
    return (f"{location}: forecast to reach {LEVEL_LABELS[peak]} (AQI {six.get('peak_aqi', '?')}) {when}"
            f"within {FORECAST_HORIZON_HOURS} hours (now AQI {analysis.get('aqi', '?')}, "
            f"{LEVEL_LABELS.get(analysis.get('level'), '?')}). Plan indoor activities.")


def _message(location: str, level: str, analysis: dict, advisory: dict) -> str:
    parts = [f"{location}: AQI {analysis.get('aqi', '?')} ({LEVEL_LABELS[level]})."]
    if advisory.get("headline"):
        parts.append(advisory["headline"])
    if advisory.get("time_note"):
        parts.append(advisory["time_note"])
    elif analysis.get("is_spike") is True:
        parts.append("Sudden spike in pollution.")
    return " ".join(parts)


def _is_simulated(readings) -> bool:
    """True when the latest reading is mock data (or unknown, to be safe)."""
    try:
        return readings[-1]["source"] != "live"
    except (TypeError, IndexError, KeyError):
        return True


def _location(readings) -> str:
    try:
        return str(readings[-1]["location"]).strip() or "Unknown location"
    except (TypeError, IndexError, KeyError):
        return "Unknown location"


def _clear_memory_on_startup(store: dict) -> None:
    """First run in this process: forget past alerts if mock data is forced (demo mode)."""
    global _startup_done
    if _startup_done:
        return
    _startup_done = True
    if _mock_forced() and store["memory"]:
        log.info("Mock data is forced, clearing alert memory so the demo scenario alerts")
        store["memory"] = {}


def _mock_forced() -> bool:
    """Same rule as the monitor: USE_MOCK=true or any MOCK_SCENARIO forces mock data."""
    use_mock = os.getenv("USE_MOCK", "").strip().lower() in {"1", "true", "yes"}
    return use_mock or bool(os.getenv("MOCK_SCENARIO", "").strip())


def _cooldown() -> timedelta:
    return timedelta(minutes=_env_number("ALERT_COOLDOWN_MINUTES", DEFAULT_COOLDOWN_MINUTES, allow_zero=True))


def _memory_max_age() -> timedelta:
    return timedelta(hours=_env_number("ALERT_MEMORY_HOURS", DEFAULT_MEMORY_HOURS, allow_zero=False))


def _env_number(name: str, default: float, allow_zero: bool) -> float:
    """A non-negative number from the environment, or the default (with a warning) if it's bad."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
        if value < 0 or (value == 0 and not allow_zero):
            raise ValueError
        return value
    except ValueError:
        log.warning("Bad %s %r, using %s", name, raw, default)
        return default


def _parse_time(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _load() -> dict:
    """{"memory": {location: {...}}, "feed": [Alert, ...]}; a fresh store if missing or broken."""
    try:
        store = json.loads(STORE_FILE.read_text(encoding="utf-8"))
        if isinstance(store.get("memory"), dict) and isinstance(store.get("feed"), list):
            return store
        log.warning("%s has an unexpected shape, starting fresh", STORE_FILE)
    except FileNotFoundError:
        pass
    except (OSError, ValueError, AttributeError) as e:
        log.warning("Could not read %s, starting fresh: %s", STORE_FILE, e)
    return {"memory": {}, "feed": []}


def _save(store: dict) -> None:
    """Write to a temp file, then swap it in, so a crash never leaves half a file."""
    try:
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, STORE_FILE)
    except OSError as e:
        log.warning("Could not save %s: %s", STORE_FILE, e)
