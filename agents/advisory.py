"""Advisory agent: turns the analysis into public guidance for each audience.

Reads: state["analysis"]
Owns:  state["advisory"]
A fixed template table (level x audience) in the style of US EPA AQI messaging, so the
advice is always correct and demo-safe. Trend and spike add a short time note. Never raises.
Wording rules: conservative, no specific medical claims, doses or treatments.
"""
import logging

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
    "moderate": {
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
    "unhealthy_sensitive": {
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
    "unhealthy": {
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
    "very_unhealthy": {
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
    "hazardous": {
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
# Use the "unhealthy" advice with an honest headline, never "Air quality is good."
FALLBACK_LEVEL = "unhealthy"
FALLBACK_HEADLINE = "Air quality data is unavailable right now. Take precautions."

# Urdu headline + public advice per level. Ask a native speaker to review before the demo.
URDU: dict[str, dict] = {
    "good": {
        "headline": "ہوا کا معیار اچھا ہے۔",
        "actions": ["معمول کی بیرونی سرگرمیاں جاری رکھیں۔"],
    },
    "moderate": {
        "headline": "ہوا کا معیار قابلِ قبول ہے۔",
        "actions": ["زیادہ تر لوگوں کے لیے بیرونی سرگرمیاں ٹھیک ہیں۔"],
    },
    "unhealthy_sensitive": {
        "headline": "حساس افراد کے لیے غیر صحت بخش۔",
        "actions": [
            "زیادہ تر لوگ بیرونی سرگرمیاں جاری رکھ سکتے ہیں۔",
            "علامات محسوس ہوں تو زیادہ وقفے لیں اور ہلکی سرگرمی کریں۔",
        ],
    },
    "unhealthy": {
        "headline": "غیر صحت بخش ہوا۔ ہر کوئی متاثر ہو سکتا ہے۔",
        "actions": [
            "طویل یا سخت بیرونی سرگرمی کم کریں اور زیادہ وقفے لیں۔",
            "باہر N95/KN95 ماسک پہنیں۔",
            "کھڑکیاں بند رکھیں اور اگر ہو سکے تو گھر میں ایئر پیوریفائر چلائیں۔",
        ],
    },
    "very_unhealthy": {
        "headline": "انتہائی غیر صحت بخش ہوا۔ صحت کا انتباہ۔",
        "actions": [
            "طویل یا سخت بیرونی سرگرمی سے گریز کریں اور سرگرمیاں گھر کے اندر منتقل کریں۔",
            "باہر جاتے وقت ہمیشہ N95/KN95 ماسک پہنیں۔",
            "کھڑکیاں اور دروازے بند رکھیں اور اگر ہو سکے تو ایئر پیوریفائر چلائیں۔",
        ],
    },
    "hazardous": {
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
RISING_NOTE = (
    "Conditions are worsening: postpone outdoor plans if you can and check again soon.",
    "حالات بگڑ رہے ہیں: اگر ممکن ہو تو بیرونی منصوبے ملتوی کریں اور جلد دوبارہ چیک کریں۔",
)
UNAVAILABLE_NOTE = (
    "No current air quality readings. Follow these precautions until data is back, and check again soon.",
    "ہوا کے معیار کی تازہ ریڈنگ دستیاب نہیں۔ ڈیٹا واپس آنے تک ان احتیاطی تدابیر پر عمل کریں اور جلد دوبارہ چیک کریں۔",
)
FALLING_NOTE = (
    "Conditions are improving, but keep following this advice until the level drops.",
    "حالات بہتر ہو رہے ہیں، لیکن سطح کم ہونے تک ان ہدایات پر عمل جاری رکھیں۔",
)


def run(state: SmogState) -> dict:
    """Graph node: advice for the current analysis."""
    return {"advisory": build_advisory(state.get("analysis"))}


def build_advisory(analysis: dict | None) -> Advisory:
    """Advice for an analysis dict. Unknown or missing input gives cautious advice."""
    analysis = analysis if isinstance(analysis, dict) else {}
    level = analysis.get("level")
    known = level in GUIDANCE
    if not known:
        if level != "unknown":  # "unknown" is expected (analysis already logged it); anything else is a bug
            log.warning("Unrecognised or missing level %r, giving cautious advice", level)
        level = FALLBACK_LEVEL

    template, urdu = GUIDANCE[level], URDU[level]
    note, note_ur = _time_note(analysis, level) if known else UNAVAILABLE_NOTE
    lead = [note] if note else []          # time context goes first so it's seen
    lead_ur = [note_ur] if note_ur else []

    return {
        "headline": template["headline"] if known else FALLBACK_HEADLINE,
        "actions": lead + template["general"],
        "audiences": {a: list(template[a]) for a in ("general", "children", "elderly", "respiratory_heart")},
        "time_note": note,
        "disclaimer": DISCLAIMER,
        "urdu": {
            "headline": urdu["headline"] if known else FALLBACK_HEADLINE_UR,
            "actions": lead_ur + urdu["actions"] + [DISCLAIMER_UR],
        },
    }


def _time_note(analysis: dict, level: str) -> tuple[str, str]:
    """(English, Urdu) note from spike flag and trend; empty strings if nothing to say."""
    if analysis.get("is_spike") is True:
        return SPIKE_NOTE
    if level == "good":  # nothing to postpone or wait for in good air
        return "", ""
    trend = analysis.get("trend")
    if trend == "rising":
        return RISING_NOTE
    if trend == "falling":
        return FALLING_NOTE
    return "", ""
