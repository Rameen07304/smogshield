"""Advisory agent: turns the analysis into public guidance.

Reads: state["analysis"]
Owns:  state["advisory"]
Rule-based for now. Swap in an LLM call here later; the output shape stays the same.
"""
from schemas import Advisory, SmogState

GUIDANCE: dict[str, Advisory] = {
    "good": {
        "headline": "Air quality is good.",
        "actions": ["Enjoy outdoor activities."],
    },
    "moderate": {
        "headline": "Air quality is acceptable.",
        "actions": ["Unusually sensitive people should limit long outdoor exertion."],
    },
    "unhealthy_sensitive": {
        "headline": "Unhealthy for sensitive groups.",
        "actions": [
            "Children, elderly and people with asthma: reduce outdoor activity.",
            "Keep windows closed during peak hours.",
        ],
    },
    "unhealthy": {
        "headline": "Unhealthy air. Everyone may feel effects.",
        "actions": [
            "Limit time outdoors.",
            "Wear an N95 mask if you must go out.",
            "Run an air purifier indoors if available.",
        ],
    },
    "very_unhealthy": {
        "headline": "Very unhealthy air. Health alert.",
        "actions": [
            "Avoid all outdoor activity.",
            "Wear an N95 mask outdoors.",
            "Schools should move activities indoors.",
        ],
    },
    "hazardous": {
        "headline": "Hazardous smog. Emergency conditions.",
        "actions": [
            "Stay indoors with windows and doors sealed.",
            "Wear an N95 mask if going out is unavoidable.",
            "Seek medical help for breathing difficulty or chest pain.",
        ],
    },
}


def run(state: SmogState) -> dict:
    analysis = state["analysis"]
    advisory = GUIDANCE[analysis["level"]]
    if analysis["trend"] == "rising" and analysis["level"] != "good":
        # copy so we don't mutate the shared GUIDANCE table
        advisory = {**advisory, "actions": advisory["actions"] + ["Conditions are worsening; check again soon."]}
    return {"advisory": advisory}
