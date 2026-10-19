"""Orchestrator: wires the agents into a LangGraph pipeline.

monitor -> forecast -> analysis -> advisory -> alert
To add an agent: write agents/<name>.py with a run(state) function, add a node and an edge here.

Run `python graph.py` for a quick self-check on mock data.
"""
from langgraph.graph import END, START, StateGraph

from agents import advisory, alert, analysis, forecast, monitor
from schemas import SmogState

builder = StateGraph(SmogState)
builder.add_node("monitor", monitor.run)
builder.add_node("forecast", forecast.run)
builder.add_node("analysis", analysis.run)
builder.add_node("advisory", advisory.run)
builder.add_node("alert", alert.run)

builder.add_edge(START, "monitor")
builder.add_edge("monitor", "forecast")
builder.add_edge("forecast", "analysis")
builder.add_edge("analysis", "advisory")
builder.add_edge("advisory", "alert")
builder.add_edge("alert", END)

graph = builder.compile()


def run_once() -> SmogState:
    return graph.invoke({})


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")  # alerts include Urdu; Windows consoles default to cp1252
    import os
    import tempfile
    from pathlib import Path

    from dotenv import load_dotenv; load_dotenv()  # same .env as app.py

    # The self-check must have no side effects: never send real Telegram messages, and keep
    # its alerts out of the real dashboard feed and alert memory (var/alerts.json).
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        os.environ.pop(key, None)

    # The temp folder (and the self-check's alerts.json in it) is deleted when this block ends
    with tempfile.TemporaryDirectory(prefix="smogshield-selfcheck-") as tmp:
        alert.STORE_FILE = Path(tmp) / "alerts.json"

        # AQI math against known breakpoint values
        assert analysis.pm25_to_aqi(9.0) == (50, "good")
        assert analysis.pm25_to_aqi(35.5) == (101, "moderate")
        assert analysis.pm25_to_aqi(125.5) == (201, "poor")
        assert analysis.pm25_to_aqi(260)[1] == "very_poor"
        assert analysis.pm25_to_aqi(275.5) == (401, "severe")
        assert analysis.pm25_to_aqi(999) == (500, "severe")
        assert analysis.pm10_to_aqi(540) == 429

        # full pipeline produces every key
        result = run_once()
        for key in ("readings", "forecast", "analysis", "advisory", "alerts"):
            assert key in result, f"missing {key}"
        print(result["analysis"], result["advisory"]["headline"], result["alerts"], sep="\n")
        print("OK")
