---
name: SmogShield
description: Live air quality for Punjab, each reading set beside the agent output that proves it.
colors:
  ground: "#f5f6f6"
  surface: "#ffffff"
  surface-sunk: "#eef0f0"
  hairline: "#e2e5e5"
  hairline-strong: "#c9cfcf"
  ink: "#16191a"
  ink-secondary: "#464e50"
  ink-tertiary: "#687073"
  proof-teal: "#0e6f68"
  proof-teal-weak: "#e2f0ee"
  proof-teal-text: "#0b5c56"
  danger: "#b42318"
  danger-weak: "#fdecea"
  danger-line: "#f0b8b2"
  warning: "#a15c07"
  success: "#1f7a45"
  simulated-bg: "#fff3d6"
  simulated-fg: "#5f3d00"
  simulated-line: "#e9c97c"
  level-good: "#4f9d69"
  level-good-ink: "#0d2416"
  level-satisfactory: "#afae4a"
  level-satisfactory-ink: "#22220a"
  level-moderate: "#d69a3a"
  level-moderate-ink: "#1e1404"
  level-poor: "#b85a30"
  level-poor-ink: "#ffffff"
  level-very-poor: "#a3374d"
  level-very-poor-ink: "#ffffff"
  level-severe: "#5b2a54"
  level-severe-ink: "#ffffff"
  level-unknown: "#5f676a"
  level-unknown-ink: "#ffffff"
typography:
  display:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, Helvetica Neue, Arial, sans-serif"
    fontSize: "96px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.04em"
    fontFeature: "tnum"
  headline:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, Helvetica Neue, Arial, sans-serif"
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, Helvetica Neue, Arial, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.55
    letterSpacing: "-0.01em"
  body:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
    fontFeature: "tnum"
  body-small:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, Helvetica Neue, Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, -apple-system, Helvetica Neue, Arial, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "normal"
  urdu:
    fontFamily: "Noto Nastaliq Urdu, serif"
    fontSize: "17px"
    fontWeight: 400
    lineHeight: 2.2
rounded:
  hairline: "1px"
  tag: "3px"
  chip: "4px"
  control: "6px"
  mark: "50%"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "24px"
  s6: "32px"
  s7: "48px"
  s8: "64px"
components:
  button:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "36px"
  button-hover:
    backgroundColor: "{colors.surface-sunk}"
  button-danger:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.danger}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "36px"
  button-danger-hover:
    backgroundColor: "{colors.danger-weak}"
  select:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 34px 0 12px"
    height: "36px"
  segment:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-secondary}"
    padding: "0 12px"
    height: "32px"
  segment-selected:
    backgroundColor: "{colors.proof-teal-weak}"
    textColor: "{colors.proof-teal-text}"
  chip:
    textColor: "{colors.ink-secondary}"
    rounded: "{rounded.chip}"
    padding: "0 8px"
    height: "24px"
  mode-badge-live:
    backgroundColor: "{colors.proof-teal-weak}"
    textColor: "{colors.proof-teal-text}"
    rounded: "{rounded.chip}"
    padding: "0 8px"
    height: "22px"
  mode-badge-simulated:
    backgroundColor: "{colors.simulated-bg}"
    textColor: "{colors.simulated-fg}"
    rounded: "{rounded.chip}"
    padding: "0 8px"
    height: "22px"
  sim-tag:
    backgroundColor: "{colors.simulated-bg}"
    textColor: "{colors.simulated-fg}"
    rounded: "{rounded.tag}"
    padding: "0 6px"
    height: "18px"
  level-tag:
    backgroundColor: "{colors.level-poor}"
    textColor: "{colors.level-poor-ink}"
    rounded: "{rounded.tag}"
    padding: "0 8px"
    height: "22px"
  level-field:
    backgroundColor: "{colors.level-poor}"
    textColor: "{colors.level-poor-ink}"
    padding: "24px"
  nav-tab:
    textColor: "{colors.ink-secondary}"
    padding: "0 12px"
    height: "60px"
  nav-tab-current:
    textColor: "{colors.ink}"
---

# Design System: SmogShield

## Overview

**Creative North Star: "Neutral Proof"**

Every reading is a claim set beside the evidence that produced it. The system is a quiet neutral sheet ruled by hairlines, on which exactly two things are allowed to carry colour: the air-quality level, as one flat field of muted ink, and the deep teal that marks selection, links, live state and completed proof. Everything else is ink on near-white.

Density is that of a well-set report rather than a dashboard of tiles: sections are separated by 1px rules, not boxed into cards; numerals are tabular everywhere so values align and update without jitter; the type works in two weights only (400 and 600). Severity is communicated firmly and calmly, always as a shape plus a word, never by colour alone. The world rejects the category default of a loud AQI tile above a grid of identical rounded cards.

Light and dark themes are both first-class, switched by `prefers-color-scheme`; the neutral scale, accent, status and simulation inks each have a dark counterpart, while the level inks stay constant across themes.

**Key Characteristics:**
- One neutral scale, one teal accent, six ordered level inks.
- Hairline-ruled sections; one raised white plane per page at most.
- 6px radius on controls only; smaller radii on tags; circles for marks.
- System sans at 400/600, tabular numerals everywhere.
- Shape plus word for every status; simulated data always labelled in amber.

## Colors

A cool, nearly colourless neutral scale carrying one deep teal accent and a calm-to-alarming ladder of muted flat inks.

### Primary
- **Proof Teal** (`proof-teal`): focus rings, the current-tab underline, selected segment and toggle borders, completed proof-ledger marks, the caret. Its weak tint (`proof-teal-weak`) fills selected segments, the live badge and a new alert's arrival flash; its text tone (`proof-teal-text`) is the link colour and the info-severity mark. Dark theme: #3fb3a6 / #12302d / #6ccfc3.

### Neutral
- **Ground** (`ground`): the page background.
- **Surface** (`surface`): the top bar, controls, and the dashboard overview band (the one raised plane).
- **Sunk Surface** (`surface-sunk`): hover fill on buttons and segments, the neutral badge, unknown-level placeholders.
- **Hairline** (`hairline`): every section rule and row divider. **Strong Hairline** (`hairline-strong`): control borders, table-header rule, unchecked proof marks, chart threshold lines.
- **Ink / Secondary / Tertiary** (`ink`, `ink-secondary`, `ink-tertiary`): primary text; supporting text and nav; labels, metadata, axis text.

### Status and honesty
- **Danger** (`danger`, with `danger-weak`, `danger-line`): critical severity, offline banners, the emergency action, failed delivery.
- **Warning** (`warning`): warning severity, the chart spike ring. **Success** (`success`): delivered alerts only.
- **Simulated Amber** (`simulated-bg`, `simulated-fg`, `simulated-line`): the honesty marker for simulated data, used on the banner, the mode badge, the sim tag, the spike chip and chart flag.

### Level inks (NCAP 2023, calm to alarming)
Sage (`level-good`), olive (`level-satisfactory`), ochre (`level-moderate`), clay (`level-poor`), madder (`level-very-poor`), plum (`level-severe`), slate (`level-unknown`). Each has a paired ink for text set on it; Poor, Very poor, Severe and Unknown take white ink.

### Named Rules
**The One Field Rule.** A level ink appears only as a flat fill that carries its own label (the hero level field, a level pill or tag) or as its segment of the NCAP scale bar. Never as a wash, a chart band, a border, or text colour.

**The Spent Accent Rule.** Teal means "selected, linked, live, or confirmed". It is never decoration and never a level.

**The Honest Amber Rule.** Anything simulated is marked in the simulated amber with a word; real data never wears amber.

## Typography

**Display / Body / Label Font:** Segoe UI Variable Text (with Segoe UI, system-ui, -apple-system, Helvetica Neue, Arial)
**Urdu Font:** Noto Nastaliq Urdu (bundled locally), right-to-left

**Character:** One sans family doing everything at two weights, made precise by tabular numerals and slight negative tracking at large sizes. Urdu is set in Nastaliq with generous leading as a first-class reading path.

### Hierarchy
- **Display** (600, 96px, 1, -0.04em; 72px under 760px): the AQI numeral in the level field, and nothing else.
- **Headline** (600, 28px, 1.2, -0.02em; 22px on phones): the hero summary sentence. Page title on How it works is 600, 36px, 1.15, -0.025em (28px on phones). Level category is 600, 22px.
- **Title** (600, 18px, -0.01em): section heads. Advice headline is 600, 20px, 1.3. Sub-heads (agent names, audiences) are 600, 15-16px.
- **Body** (400, 15px, 1.55): default text; supporting copy at 14px; long text capped near 70ch.
- **Label** (600, 12-13px, normal tracking, sentence case): field labels, badges, tags, table heads, metadata.
- **Urdu** (400, 17px list / 22px headline, line-height 2.2 / 2): advice in Urdu.

### Named Rules
**The Two Weights Rule.** 400 for reading, 600 for anything that names or claims. No other weights.

**The Tabular Rule.** `font-variant-numeric: tabular-nums` is set on the body and inherited everywhere, so live values never shift width.

**The Sentence Case Rule.** Labels, tags and badges are sentence case and untracked. No uppercase, no letter-spaced small labels.

## Layout

A 1280px page (`--page`) with 32px gutters (16px under 760px); full-bleed bars align to the same edge via `max(gutter, (100% - page) / 2)`. The spacing scale is 4, 8, 12, 16, 24, 32, 48, 64px; sections use 32px vertical padding and 24px head-to-content gaps.

The dashboard overview is a 7/5 split: the claim (a 260px level field beside the headline, NCAP scale and PM facts) and the proof ledger, divided by a vertical hairline. Below, an 8/4 split for chart and alert feed, then advice full width (4/8 internal split). How it works uses a five-column ruled flow; History a full-width ruled table. Columns collapse in steps at 1320px (top-bar controls wrap to a second row), 1180px (overview stacks, flow goes to three), 900px (chart, feed, advice stack) and 760px (single column, tabs scroll horizontally, table becomes labelled rows).

## Elevation & Depth

Flat. There are no drop shadows. Depth is tonal: a near-white ground, white surfaces for the top bar and controls, and the dashboard overview band as the page's one raised white plane, bled to the window edges and closed with a hairline. Structure comes from 1px hairlines, never from boxes or shadows. `box-shadow` appears only as a drawing tool: the 2px inset tab underline, the 1px inset ring on a pressed toggle, the 2px surface halo round the scale marker, and the overview bleed.

### Named Rules
**The One Plane Rule.** At most one raised white plane per page; everything else sits on the ground and is divided by hairlines.

## Shapes

Square by default. Controls (buttons, selects, segmented groups, the language toggle) take a 6px radius; chips and mode badges 4px; small tags and the chart flag 3px. The level field, banners and sections are square. Circles are reserved for marks: proof-ledger checks, step numbers, status dots. Severity shapes: circle for info, triangle for warning, near-square for critical, drawn in CSS.

## Components

### Buttons
Quiet and outlined; the emergency action is the only coloured one.
- **Shape:** 6px radius, 36px tall, 14px side padding, 600 14px label.
- **Default:** white fill, strong-hairline border, ink text; hover fills with the sunk surface; active nudges down 1px.
- **Danger:** danger text and danger-line border; hover fills danger-weak with a full danger border.
- **Plain:** an underlined teal text button with no box.

### Selects and fields
36px, 6px radius, strong-hairline border, white fill, a drawn chevron; hover darkens the border to tertiary ink. Labels sit beside the field in 600 13px tertiary ink (stacked above on phones).

### Selection (segmented filters and language toggle)
One treatment for every choice: joined 32px segments in white with strong hairlines; the selected segment takes the teal-weak fill, teal border and teal text. Severity filters prefix the CSS shape for their level.

### Chips, badges and tags
- **Chip:** 24px, 4px radius, hairline-outlined, 600 12px secondary ink. The spike chip wears simulated amber with a dot.
- **Mode badge:** 22px, 4px radius, dot plus word: teal-weak when live (the dot breathes unless motion is reduced), amber when simulated, danger-weak when offline.
- **Sim tag:** 18px amber tag reading "Simulated".
- **Level pill / tag:** flat level ink with its paired text ink, 3px radius, 26px / 22px.
- **Severity mark:** a CSS shape plus a word in the severity colour, no box.

### Navigation
A 60px white top bar: shield mark and wordmark (600 17px) with the mode badge, then text tabs in 600 14px secondary ink. Hover draws a strong-hairline underline, the current page a 2px teal underline. On phones tabs are 48px and scroll horizontally.

### Level field (signature)
A square flat block in the current level ink holding a label, the 96px AQI numeral and the category word, colour-transitioning over 0.5s. Beside it, the NCAP scale bar: six proportional segments 8px tall with a 3px ink marker that slides to the reading.

### Proof ledger (signature)
Five hairline-ruled rows (Monitor, Forecast, Analysis, Advisory, Alert): an 18px circle mark, agent name and role, and the agent's output right-aligned. When an output changes, rows confirm in pipeline order, 220ms apart: each goes active (teal ring, teal-weak fill) then done (solid teal with a white check drawn in CSS). Reduced motion sets all rows done at once.

### Chart
Ink polyline (2px) with white-filled points, the latest larger; values labelled above points. NCAP thresholds are neutral dashed strong hairlines (3/4 dash) with band names at the right in tertiary ink. A spike adds a warning-coloured ring and an amber flag.

### Alert feed and history
Hairline-divided rows: severity mark, optional sim tag, message, tertiary metadata. The dashboard shows the newest four and links to History; new arrivals flash teal-weak once. History is a ruled table with a sticky header on the ground colour, delivery status as dot plus word.

## Do's and Don'ts

### Do:
- **Do** divide sections and rows with 1px hairlines (`hairline`) instead of boxing them.
- **Do** give every level fill its paired ink and its name, and keep levels ordered sage, olive, ochre, clay, madder, plum.
- **Do** pair every status with a CSS shape and a word.
- **Do** use the single selection treatment (teal-weak fill, teal border and text) for any choice control.
- **Do** label simulated data in amber, in words, wherever it appears.
- **Do** keep numerals tabular and weights at 400/600.
- **Do** respect `prefers-reduced-motion`: the proof ledger, live dot, scale marker and alert flash all stand still.

### Don't:
- **Don't** build grids of rounded, shadowed cards, or add drop shadows.
- **Don't** wash chart regions, borders or text in level colours; thresholds stay neutral dashed hairlines.
- **Don't** spend teal on decoration, headings or levels.
- **Don't** use uppercase or letter-spaced labels, eyebrows above headings, or unicode glyphs as icons.
- **Don't** raise more than one white plane on a page.
- **Don't** round sections or the level field; radius belongs to controls and tags.
