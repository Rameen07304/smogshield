"""Orchestrator: wires the agents into a LangGraph pipeline.

monitor -> analysis -> advisory -> alert
To add an agent: write agents/<name>.py with a run(state) function, add a node and an edge here.

Run `python graph.py` for a quick self-check on mock data.
"""
from langgraph.graph import END, START, StateGraph

from agents import advisory, alert, analysis, monitor
from schemas import SmogState

builder = StateGraph(SmogState)
builder.add_node("monitor", monitor.run)
builder.add_node("analysis", analysis.run)
builder.add_node("advisory", advisory.run)
builder.add_node("alert", alert.run)

builder.add_edge(START, "monitor")
builder.add_edge("monitor", "analysis")
builder.add_edge("analysis", "advisory")
builder.add_edge("advisory", "alert")
builder.add_edge("alert", END)

graph = builder.compile()


def run_once() -> SmogState:
    return graph.invoke({})


if __name__ == "__main__":
    # AQI math against known EPA values
    assert analysis.pm25_to_aqi(9.0) == (50, "good")
    assert analysis.pm25_to_aqi(35.5) == (101, "unhealthy_sensitive")
    assert analysis.pm25_to_aqi(260)[1] == "hazardous"
    assert analysis.pm25_to_aqi(999) == (500, "hazardous")

    # full pipeline produces every key
    result = run_once()
    for key in ("readings", "analysis", "advisory", "alerts"):
        assert key in result, f"missing {key}"
    print(result["analysis"], result["advisory"]["headline"], result["alerts"], sep="\n")
    print("OK")
