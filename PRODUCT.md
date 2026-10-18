# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
- **Primary (now):** hackathon judges watching a projected live demo (Oct 17–19, 2026). They need to grasp within seconds what the system does, that it is real, and that the agents cooperate.
- **Primary (real use):** residents of Punjab, Pakistan (Lahore first), often on a phone, checking the air before going out, sending children to school, or exercising. Includes parents, the elderly, people with asthma or heart disease, and outdoor workers. Many read Urdu.

## Product Purpose
SmogShield is a modular multi-agent system that monitors air quality and coordinates smog response in real time: it reads PM2.5/PM10, scores the air, forecasts the next hours, writes guidance per group (English and Urdu), and raises alerts. Success: a resident knows how the air is right now, whether it is getting worse, and what to do; a judge sees the agent pipeline doing that live.

## Positioning
Not just an AQI number: five cooperating agents (Monitor → Forecast → Analysis → Advisory → Alert) turn model data into group-specific, bilingual guidance and predictive alerts, labelled honestly as model estimates or simulations. Categories follow Pakistan's National Clean Air Policy 2023.

## Operating Context
- Three screens: Live dashboard (`/`), How it works (`/how`), Alert history (`/history`).
- Polls `/api/status` every 5 s; demo controls switch city and scripted scenarios (good → severe, spike) and trigger a simulated emergency.
- Demo runs locally on 127.0.0.1, projected on a screen; real use is a phone in daylight or a laptop indoors.
- Winter smog season (Oct–Feb) is when it matters most.

## Capabilities and Constraints
- Plain HTML/CSS/JS in `web/`, served by FastAPI; no build step, no CDNs, fonts served locally (Noto Nastaliq Urdu bundled, OFL).
- Levels: good, satisfactory, moderate, poor, very_poor, severe, unknown (NCAP 2023 categories; AQI number via US EPA method, max of PM2.5 and PM10).
- Data: Open-Meteo (CAMS model estimates), hourly; mock scenarios when forced or offline.
- Alerts: info / warning / critical; kinds current and forecast; optional Telegram delivery.
- Light and dark themes via `prefers-color-scheme`.

## Brand Commitments
- Name: SmogShield, with the existing shield mark.
- Level colours may be redesigned (user decision, Oct 18 2026), but must stay ordered from calm to alarming and distinguishable without colour alone.
- Must not feel alarmist/panicky or overly technical.

## Evidence on Hand
- Live and simulated data from the running app; NCAP 2023 document (Table 1 categories, Table 2 targets).
- No testimonials, users, partners, or official endorsements exist; do not invent any.

## Product Principles
1. Honest first: model estimates and simulations are always labelled as such.
2. Calm clarity: severity is communicated firmly, never with panic.
3. Action over numbers: every reading leads to what to do, per group.
4. Bilingual by default: Urdu is a first-class reading path, not a translation footnote.
5. Show the agents working: the pipeline is visible, not hidden behind the result.

## Accessibility & Inclusion
- Readable in daylight on phones and on a projector; WCAG AA contrast.
- Level never conveyed by colour alone (text label always present).
- Urdu set right-to-left in Nastaliq.
- Respects reduced motion.
