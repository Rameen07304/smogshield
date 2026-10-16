# SmogShield: Team Plan (Hackathon, Oct 17–19)

5 people, 3 days. Goal: **a working live demo** of agents spotting a smog spike and alerting the public.

Repo: https://github.com/Rameen07304/smogshield. Read the [README](README.md) first and get `python graph.py` printing `OK` on your machine.

## How we work

- **One owner per file.** Only edit files you own. That's how 5 people avoid merge conflicts.
- **`schemas.py` is shared.** Want to change a contract? Post in the group chat first, and the Lead merges it.
- **Branch per task:** `git checkout -b <yourname>/<task>`, then open a PR to `main`. Keep PRs small.
- **Before every PR:** run `python graph.py` and make sure it prints `OK`.
- **Never commit `.env` or API keys.** This repo is public. Put keys in `.env` only; it's gitignored.
- **The demo must always work on mock data.** A real API is a bonus, not a dependency.

## Who does what

| # | Role | Name | Owns |
|---|------|------|------|
| 1 | Lead / Orchestrator | Rameen | `graph.py`, `schemas.py`, `app.py`, merges PRs |
| 2 | Monitor agent | Halima | `agents/monitor.py`, `data/` |
| 3 | Analysis agent | Fatima | `agents/analysis.py` |
| 4 | Advisory agent | Rida | `agents/advisory.py` |
| 5 | Alert agent + Dashboard | Dania | `agents/alert.py`, `web/` |

1. Lead / Orchestrator
- Review and merge PRs; keep `main` always runnable.
- Own `schemas.py`; approve contract changes.
- Optional: LangGraph conditional routing (for example, skip the alert node when air is good).
- Write the demo script (what we click and say, minute by minute) and run rehearsals.
- Prepare the pitch slides with the team.

2. Monitor agent (data)
- Get an OpenAQ API key and find a working PM2.5 location for our city.
- Make sure the OpenAQ → mock fallback works when the network is off.
- Stretch: multiple cities/stations, or a "demo mode" toggle that forces the smog spike on stage.
- Contract: returns `{"readings": [Reading, ...]}`, oldest first.

3. Analysis agent
- Verify AQI math against an official EPA AQI calculator; add PM10 AQI (take the worse of the two).
- Improve trend detection (for example, rate of change per hour).
- Stretch: a simple next-hours forecast (a moving average is fine).
- Contract: returns `{"analysis": Analysis}`.

4. Advisory agent
- Improve guidance text for each level; add advice for specific groups (kids, elderly, asthma, outdoor workers).
- Stretch: generate guidance with an LLM (keep the rule-based version as fallback) and/or add an Urdu translation.
- Contract: returns `{"advisory": Advisory}`.

5. Alert agent + Dashboard
- Tune alert rules (for example, don't repeat the same alert every poll).
- Dashboard: add a PM2.5/AQI chart over time, a nicer layout, a clear alert banner.
- Stretch: a real channel (Telegram bot) behind an env var.
- Contract: returns `{"alerts": [Alert, ...]}`; dashboard reads `GET /api/status`.

## Timeline

| Day | Date | Target |
|-----|------|--------|
| 1 | Fri Oct 17 | Everyone set up and running. Each owner ships one improvement to their agent. Contract changes agreed **by end of day 1**. |
| 2 | Sat Oct 18 | Core features + stretch goals. Integrate continuously (merge small, merge often). End of day: full demo runs end to end. |
| 3 | Sun Oct 19 | **Feature freeze at noon.** Afternoon: bug fixes only, rehearse the demo 2–3 times, finish slides. |

## Demo story (draft, Lead refines)
1. Dashboard shows clean air in our city.
2. Smog builds: AQI climbs, the trend says "rising", and an early info alert appears.
3. Spike hits "very unhealthy / hazardous": a critical alert and emergency guidance.
4. Explain the agents: each one is an independent module and they hand off through shared contracts.
