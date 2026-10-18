---
version: 1
slug: "web-index-html"
primary_target: "web/index.html"
related_targets: ["web/how.html","web/history.html"]
---

# SmogShield web app (Live dashboard, How it works, History)

Mode: Operate. Audience: hackathon judges on a projector (first), Punjab residents on phones (real use). Job: know the air now, whether it is getting worse, what to do; see the five agents doing it. Constraints: plain HTML/CSS/JS, no CDNs, system fonts + bundled Noto Nastaliq Urdu, all element IDs used by app.js/how.js/history.js preserved. Calm, never alarmist; never too technical. Level colours redesigned (user decision), ordered calm to alarming, always paired with a text label.

## Direction contract

THESIS: Every reading is a claim set beside the agent output that proves it. Refuses the category default of a loud AQI tile above a grid of identical rounded cards.

OWN-WORLD: One neutral scale (near-white #F5F6F6 ground, white raised surfaces, #E2E5E5 hairlines, #16191A ink), one deep teal accent (#0E6F68) spent only on selection, links, live state and completed proof marks; level colours as muted flat inks (sage, olive, ochre, clay, madder, plum) that own exactly one field; hairline-ruled sections instead of cards; 6px radius on controls only; system sans at 400/600; tabular numerals everywhere.

STORY: The visitor reads the air and the headline advice at once, sees beside it five proof rows (Monitor, Forecast, Analysis, Advisory, Alert) confirming how that answer was produced, then scans the trend, the advice for their group, and the alert log.

FIRST VIEWPORT: 60px white top bar (shield + wordmark + live/simulated badge, underline tabs, city and scenario selects, outlined emergency action). Below, a 12-column overview: left 7 columns the claim (flat level field with the AQI numeral at 96px and its category, then headline, NCAP scale, PM facts); right 5 columns the proof ledger. Chart and alert log start just above the fold.

FORM: Neutral Proof, the dealt challenger chosen over the assigned direction (the user's choice); seed:82c6d261d653132b. Signature move: on every refresh the proof ledger confirms row by row in pipeline order, each row gaining a teal check as its agent's output lands.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
