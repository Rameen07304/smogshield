"""Advisory agent: turns the analysis into public guidance for each audience.

Reads: state["analysis"], state["forecast"]
Owns:  state["advisory"]
A fixed template table (level x audience) in the style of US EPA AQI messaging, so the
advice is always correct and demo-safe. Trend and spike add a short time note; the forecast
adds a forecast note (worse soon / better by when / best time to go out). Never raises.
Wording rules: conservative, no specific medical claims, doses or treatments.
"""
import logging
from datetime import datetime, timedelta, timezone

from schemas import Advisory, SmogState

log = logging.getLogger(__name__)

DISCLAIMER = "General guidance, not medical advice. If you have symptoms or a health condition, follow your doctor's advice."
DISCLAIMER_UR = "یہ عمومی رہنمائی ہے، طبی مشورہ نہیں۔ علامات یا کسی بیماری کی صورت میں اپنے ڈاکٹر کے مشورے پر عمل کریں۔"

# level -> headline + advice per audience. Advice gets stricter as the level rises.
GUIDANCE: dict[str, dict] = {
    "good": {
        "headline": "Air quality is good.",
        "general": ["Enjoy normal outdoor activities."],
        "children": ["Outdoor play and school sports can go ahead as normal."],
        "elderly": ["Normal outdoor activities are fine."],
        "respiratory_heart": ["No special precautions needed. Follow your usual care plan."],
    },
    "satisfactory": {
        "headline": "Air quality is acceptable.",
        "general": ["Outdoor activities are fine for most people."],
        "children": [
            "Outdoor play is fine.",
            "Watch children who are unusually sensitive to pollution for coughing or shortness of breath.",
        ],
        "elderly": ["Outdoor activities are fine. If you are unusually sensitive, keep long or strenuous outings shorter."],
        "respiratory_heart": [
            "If you are unusually sensitive, make outdoor activities shorter and less intense.",
            "Watch for symptoms such as coughing or shortness of breath.",
        ],
    },
    "moderate": {
        "headline": "Unhealthy for sensitive groups.",
        "general": [
            "Most people can continue outdoor activities.",
            "If you notice symptoms, take more breaks and do less intense activities.",
        ],
        "children": [
            "Reduce long or intense outdoor activity and take more breaks.",
            "Schools: shorten strenuous PE and sports, or move them indoors.",
        ],
        "elderly": [
            "Reduce long or intense outdoor activity.",
            "Keep windows closed during peak pollution hours.",
        ],
        "respiratory_heart": [
            "Reduce long or intense outdoor activity.",
            "Follow your asthma or heart action plan and keep your prescribed medicines handy.",
            "Watch for symptoms such as coughing, wheezing, chest tightness or unusual tiredness.",
        ],
    },
    "poor": {
        "headline": "Unhealthy air. Everyone may feel effects.",
        "general": [
            "Reduce long or intense outdoor activity and take more breaks.",
            "Wear an N95/KN95 mask outdoors.",
            "Keep windows closed and run an air purifier indoors if you have one.",
        ],
        "children": [
            "Avoid long or intense outdoor activity.",
            "Schools: move PE, sports and assemblies indoors.",
        ],
        "elderly": [
            "Avoid long or intense outdoor activity and keep outings short.",
            "Wear an N95/KN95 mask outdoors.",
        ],
        "respiratory_heart": [
            "Avoid long or intense outdoor activity and stay indoors where possible.",
            "Follow your action plan and keep your prescribed medicines handy.",
            "Contact a doctor if your symptoms get worse.",
        ],
    },
    "very_poor": {
        "headline": "Very unhealthy air. Health alert.",
        "general": [
            "Avoid long or intense outdoor activity and move activities indoors.",
            "Wear an N95/KN95 mask whenever you go outside.",
            "Keep windows and doors closed and run an air purifier if you have one.",
        ],
        "children": [
            "Keep children indoors and cancel outdoor play.",
            "Schools: hold all activities indoors with windows closed.",
        ],
        "elderly": [
            "Stay indoors as much as possible.",
            "Wear an N95/KN95 mask if you must go out.",
        ],
        "respiratory_heart": [
            "Stay indoors and avoid all outdoor physical activity.",
            "Follow your action plan and keep your prescribed medicines handy.",
            "Seek medical help if your symptoms get worse.",
        ],
    },
    "severe": {
        "headline": "Hazardous smog. Emergency conditions.",
        "general": [
            "Stay indoors with windows and doors closed.",
            "Avoid all outdoor activity.",
            "Wear an N95/KN95 mask if going out is unavoidable.",
            "Run an air purifier indoors if you have one.",
        ],
        "children": [
            "Keep children indoors with windows closed.",
            "Schools: no outdoor activities; follow official closure notices.",
        ],
        "elderly": [
            "Stay indoors with windows and doors closed.",
            "Check on elderly relatives and neighbours.",
        ],
        "respiratory_heart": [
            "Stay indoors with windows and doors closed and avoid any exertion.",
            "Follow your action plan and keep your prescribed medicines handy.",
            "Seek medical help urgently for breathing difficulty or chest pain.",
        ],
    },
}

# "unknown" (no valid readings) or any missing/unrecognised level: be cautious and say so.
# Use the "poor" advice with an honest headline, never "Air quality is good."
FALLBACK_LEVEL = "poor"
FALLBACK_HEADLINE = "Air quality data is unavailable right now. Take precautions."

# Urdu headline + public advice per level. Ask a native speaker to review before the demo.
URDU: dict[str, dict] = {
    "good": {
        "headline": "ہوا کا معیار اچھا ہے۔",
        "actions": ["معمول کی بیرونی سرگرمیاں جاری رکھیں۔"],
    },
    "satisfactory": {
        "headline": "ہوا کا معیار قابلِ قبول ہے۔",
        "actions": ["زیادہ تر لوگوں کے لیے بیرونی سرگرمیاں ٹھیک ہیں۔"],
    },
    "moderate": {
        "headline": "حساس افراد کے لیے غیر صحت بخش۔",
        "actions": [
            "زیادہ تر لوگ بیرونی سرگرمیاں جاری رکھ سکتے ہیں۔",
            "علامات محسوس ہوں تو زیادہ وقفے لیں اور ہلکی سرگرمی کریں۔",
        ],
    },
    "poor": {
        "headline": "غیر صحت بخش ہوا۔ ہر کوئی متاثر ہو سکتا ہے۔",
        "actions": [
            "طویل یا سخت بیرونی سرگرمی کم کریں اور زیادہ وقفے لیں۔",
            "باہر N95/KN95 ماسک پہنیں۔",
            "کھڑکیاں بند رکھیں اور اگر ہو سکے تو گھر میں ایئر پیوریفائر چلائیں۔",
        ],
    },
    "very_poor": {
        "headline": "انتہائی غیر صحت بخش ہوا۔ صحت کا انتباہ۔",
        "actions": [
            "طویل یا سخت بیرونی سرگرمی سے گریز کریں اور سرگرمیاں گھر کے اندر منتقل کریں۔",
            "باہر جاتے وقت ہمیشہ N95/KN95 ماسک پہنیں۔",
            "کھڑکیاں اور دروازے بند رکھیں اور اگر ہو سکے تو ایئر پیوریفائر چلائیں۔",
        ],
    },
    "severe": {
        "headline": "خطرناک اسموگ۔ ہنگامی صورتحال۔",
        "actions": [
            "کھڑکیاں اور دروازے بند کر کے گھر کے اندر رہیں۔",
            "تمام بیرونی سرگرمیوں سے گریز کریں۔",
            "اگر باہر جانا ناگزیر ہو تو N95/KN95 ماسک پہنیں۔",
            "اگر ہو سکے تو گھر میں ایئر پیوریفائر چلائیں۔",
        ],
    },
}
FALLBACK_HEADLINE_UR = "ہوا کے معیار کا ڈیٹا اس وقت دستیاب نہیں۔ احتیاط کریں۔"

# Time context from trend and spike: (English, Urdu)
SPIKE_NOTE = (
    "Sudden spike in pollution: postpone outdoor plans and check again within the hour.",
    "آلودگی میں اچانک اضافہ: بیرونی منصوبے ملتوی کریں اور ایک گھنٹے میں دوبارہ چیک کریں۔",
)
RISING_NOTE = (  # from "moderate" upward
    "Conditions are worsening: postpone outdoor plans if you can and check again soon.",
    "حالات بگڑ رہے ہیں: اگر ممکن ہو تو بیرونی منصوبے ملتوی کریں اور جلد دوبارہ چیک کریں۔",
)
GENTLE_RISING_NOTE = (  # good / satisfactory: outdoor activity is still fine, so don't say postpone
    "Air quality is trending worse; keep an eye on updates.",
    "ہوا کا معیار خراب ہونے کی طرف جا رہا ہے؛ تازہ معلومات پر نظر رکھیں۔",
)
GENTLE_LEVELS = {"good", "satisfactory"}
UNAVAILABLE_NOTE = (
    "No current air quality readings. Follow these precautions until data is back, and check again soon.",
    "ہوا کے معیار کی تازہ ریڈنگ دستیاب نہیں۔ ڈیٹا واپس آنے تک ان احتیاطی تدابیر پر عمل کریں اور جلد دوبارہ چیک کریں۔",
)
FALLING_NOTE = (
    "Conditions are improving, but keep following this advice until the level drops.",
    "حالات بہتر ہو رہے ہیں، لیکن سطح کم ہونے تک ان ہدایات پر عمل جاری رکھیں۔",
)


# ---------- forecast wording (deterministic templates; times in the cities' local time) ----------

LOCAL_UTC_OFFSET = timedelta(hours=5)   # every monitored city is in Pakistan Standard Time (no DST)
LEVEL_ORDER = ["good", "satisfactory", "moderate", "poor", "very_poor", "severe"]
LEVEL_NAMES = {   # (English, Urdu) for use inside a sentence
    "good": ("Good", "اچھا"),
    "satisfactory": ("Satisfactory", "قابل قبول"),
    "moderate": ("Moderate", "درمیانہ"),
    "poor": ("Poor", "خراب"),
    "very_poor": ("Very Poor", "بہت خراب"),
    "severe": ("Severe", "شدید"),
}
WORSEN_NOTE = (
    "Air quality is forecast to worsen over the next 6 hours, reaching {level} around {time}; plan indoor activities.",
    "اگلے 6 گھنٹوں میں ہوا کا معیار خراب ہونے کی پیش گوئی ہے، تقریباً {time} تک {level}؛ گھر کے اندر سرگرمیوں کی منصوبہ بندی کریں۔",
)
SLIGHTLY_WORSE_NOTE = (
    "Air quality is forecast to get a little worse over the next 6 hours; keep an eye on updates.",
    "اگلے 6 گھنٹوں میں ہوا کا معیار تھوڑا خراب ہونے کی پیش گوئی ہے؛ تازہ معلومات پر نظر رکھیں۔",
)
IMPROVE_NOTE = ("Expected to improve by {when}.", "{when} تک بہتری کی توقع ہے۔")
NO_IMPROVEMENT_NOTE = ("Not expected to improve in the next 24 hours.", "اگلے 24 گھنٹوں میں بہتری کی توقع نہیں۔")
BEST_TIME_NOTE = ("Best time to go outside: {day}{start}–{end}.", "باہر جانے کا بہترین وقت: {day}{start}–{end}۔")
TOMORROW = ("tomorrow ", "کل ")   # prefix when the best window is on the next local day
NO_CLEAN_WINDOW_NOTE = (
    "Even the cleanest hours in the next 24 hours stay {level}; limit time outdoors.",
    "اگلے 24 گھنٹوں کے صاف ترین اوقات بھی {level} رہیں گے؛ باہر کم وقت گزاریں۔",
)
# (English, Urdu) for "by <when>", by local hour, for today and for tomorrow
PARTS_OF_DAY = [  # (first hour, today, tomorrow)
    (0, ("tonight", "آج رات"), ("overnight", "رات گئے")),
    (5, ("this morning", "آج صبح"), ("tomorrow morning", "کل صبح")),
    (12, ("this afternoon", "آج دوپہر"), ("tomorrow afternoon", "کل دوپہر")),
    (17, ("this evening", "آج شام"), ("tomorrow evening", "کل شام")),
    (21, ("tonight", "آج رات"), ("tomorrow night", "کل رات")),
]


def run(state: SmogState) -> dict:
    """Graph node: advice for the current analysis, with forecast context when there is one."""
    return {"advisory": build_advisory(state.get("analysis"), state.get("forecast"))}


def build_advisory(analysis: dict | None, forecast: dict | None = None) -> Advisory:
    """Advice for an analysis dict. Unknown or missing input gives cautious advice.

    The forecast only adds a note (forecast_note, also listed after the time note); it never
    changes the headline, the per-audience advice or their severity.
    """
    analysis = analysis if isinstance(analysis, dict) else {}
    level = analysis.get("level")
    known = level in GUIDANCE
    if not known:
        if level != "unknown":  # "unknown" is expected (analysis already logged it); anything else is a bug
            log.warning("Unrecognised or missing level %r, giving cautious advice", level)
        level = FALLBACK_LEVEL

    template, urdu = GUIDANCE[level], URDU[level]
    note, note_ur = _time_note(analysis, level) if known else UNAVAILABLE_NOTE
    try:
        f_note, f_note_ur = forecast_note(level if known else "unknown", forecast)
    except Exception:  # a malformed forecast must never cost the advice
        log.exception("Could not word the forecast; leaving the forecast note out")
        f_note, f_note_ur = "", ""
    lead = [n for n in (note, f_note) if n]       # time context first, then the forecast, so both are seen
    lead_ur = [n for n in (note_ur, f_note_ur) if n]

    return {
        "headline": template["headline"] if known else FALLBACK_HEADLINE,
        "actions": lead + template["general"],
        "audiences": {a: list(template[a]) for a in ("general", "children", "elderly", "respiratory_heart")},
        "time_note": note,
        "forecast_note": f_note,
        "disclaimer": DISCLAIMER,
        "urdu": {
            "headline": urdu["headline"] if known else FALLBACK_HEADLINE_UR,
            "actions": lead_ur + urdu["actions"] + [DISCLAIMER_UR],
            "forecast_note": f_note_ur,
        },
    }


def forecast_note(level: str, forecast: dict | None) -> tuple[str, str]:
    """(English, Urdu) forecast sentence(s) for the current level; ("", "") when there is nothing to say."""
    if level not in LEVEL_ORDER or not isinstance(forecast, dict) or not forecast.get("next_6h"):
        return "", ""
    rank = LEVEL_ORDER.index(level)
    now = _parse_utc(forecast.get("generated_at")) or datetime.now(timezone.utc)
    sentences: list[tuple[str, str]] = []

    # 1. Getting worse within 6 hours, or (already poor air) when it gets better
    six = forecast["next_6h"]
    peak_rank = LEVEL_ORDER.index(six["peak_level"]) if six["peak_level"] in LEVEL_ORDER else rank
    if peak_rank > rank:
        if peak_rank >= LEVEL_ORDER.index("moderate"):
            name, name_ur = LEVEL_NAMES[six["peak_level"]]
            # when that level is first reached (the time to plan around), not when it peaks
            onset = next((p["time"] for p in forecast.get("hourly") or []
                          if p.get("hours_ahead", 99) < six.get("hours", 6) and p.get("level") in LEVEL_ORDER
                          and LEVEL_ORDER.index(p["level"]) >= peak_rank), six["peak_time"])
            at = _local_clock(onset)
            sentences.append((WORSEN_NOTE[0].format(level=name, time=at), WORSEN_NOTE[1].format(level=name_ur, time=at)))
        else:
            sentences.append(SLIGHTLY_WORSE_NOTE)
    elif rank >= LEVEL_ORDER.index("moderate"):
        better = next((p for p in forecast.get("hourly") or []
                       if p.get("hours_ahead", 0) >= 1 and p.get("level") in LEVEL_ORDER
                       and LEVEL_ORDER.index(p["level"]) < rank), None)
        if better:
            when, when_ur = _when(better["time"], now)
            sentences.append((IMPROVE_NOTE[0].format(when=when), IMPROVE_NOTE[1].format(when=when_ur)))
        else:
            sentences.append(NO_IMPROVEMENT_NOTE)

    # 2. The best time to go out, once the air is not simply good
    best = forecast.get("best_time")
    if best and rank >= LEVEL_ORDER.index("satisfactory") and best.get("level") in LEVEL_ORDER:
        if LEVEL_ORDER.index(best["level"]) >= LEVEL_ORDER.index("poor"):
            name, name_ur = LEVEL_NAMES[best["level"]]
            sentences.append((NO_CLEAN_WINDOW_NOTE[0].format(level=name), NO_CLEAN_WINDOW_NOTE[1].format(level=name_ur)))
        else:
            start, end = _local_clock(best["start"]), _local_clock(best["end"])
            local_now = now.astimezone(timezone.utc) + LOCAL_UTC_OFFSET
            day, day_ur = TOMORROW if _local(best["start"]).date() > local_now.date() else ("", "")
            sentences.append((BEST_TIME_NOTE[0].format(day=day, start=start, end=end),
                              BEST_TIME_NOTE[1].format(day=day_ur, start=start, end=end)))

    return " ".join(s[0] for s in sentences), " ".join(s[1] for s in sentences)


def _parse_utc(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _local(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc) + LOCAL_UTC_OFFSET


def _local_clock(value: str) -> str:
    """ISO UTC time -> "HH:MM" in local time."""
    return _local(value).strftime("%H:%M")


def _when(value: str, now: datetime) -> tuple[str, str]:
    """(English, Urdu) part of the day for a future time: "this evening", "tomorrow morning", or a date."""
    local, local_now = _local(value), now.astimezone(timezone.utc) + LOCAL_UTC_OFFSET
    days_ahead = (local.date() - local_now.date()).days
    if days_ahead > 1:
        return local.strftime("%d %b, %H:%M"), local.strftime("%d/%m، %H:%M")
    part = [p for p in PARTS_OF_DAY if local.hour >= p[0]][-1]
    return part[1] if days_ahead == 0 else part[2]


def _time_note(analysis: dict, level: str) -> tuple[str, str]:
    """(English, Urdu) note from spike flag and trend; empty strings if nothing to say."""
    if analysis.get("is_spike") is True:
        return SPIKE_NOTE
    trend = analysis.get("trend")
    if trend == "rising":
        return GENTLE_RISING_NOTE if level in GENTLE_LEVELS else RISING_NOTE
    if level == "good":  # nothing to wait for when the air is already good
        return "", ""
    if trend == "falling":
        return FALLING_NOTE
    return "", ""
