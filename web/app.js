// SmogShield dashboard: polls /api/status and renders each panel.
// Rules: textContent only (never inject API data as HTML), keep the last good data on screen
// when a poll fails, and never leave a panel blank.
"use strict";

const POLL_MS = 5000;          // backend caches live data for 10 min, so this is cheap
const REQUEST_TIMEOUT_MS = 15000;

const LEVELS = {
  good:                { label: "Good" },
  moderate:            { label: "Moderate" },
  unhealthy_sensitive: { label: "Unhealthy for sensitive groups" },
  unhealthy:           { label: "Unhealthy" },
  very_unhealthy:      { label: "Very unhealthy" },
  hazardous:           { label: "Hazardous" },
  unknown:             { label: "Data unavailable" },
};
const SCENARIO_LABELS = {
  live: "Live data",
  good: "Good",
  moderate: "Moderate",
  unhealthy_sensitive: "Unhealthy for sensitive groups",
  unhealthy: "Unhealthy",
  very_unhealthy: "Very unhealthy",
  hazardous: "Hazardous",
  spike: "Spike: smog builds, then clears",
};
const TREND_WORDS = { rising: "rising", falling: "falling", stable: "steady" };
const TREND_ARROWS = { rising: "↑", falling: "↓", stable: "→" };

const $ = (id) => document.getElementById(id);
let lastGood = null;  // the last /api/status that rendered fine

// ---------- helpers ----------

/** fetch JSON with a timeout; throws on network errors and non-2xx responses */
async function getJSON(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

const localTime = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const levelOf = (analysis) => (analysis && analysis.level in LEVELS ? analysis.level : "unknown");

// ---------- panels ----------

function renderHero(s) {
  const a = s.analysis || {};
  const level = levelOf(a);
  const known = level !== "unknown";
  const latest = s.readings?.at(-1);

  $("hero").dataset.level = level;
  $("hero-aqi").textContent = known && a.aqi != null ? a.aqi : "--";
  $("hero-category").textContent = LEVELS[level].label;

  const place = $("hero-place");
  place.replaceChildren();
  if (latest) {
    const city = document.createElement("strong");
    city.textContent = latest.location;
    place.append(city, ` · reading for ${localTime(latest.timestamp)}`);
  } else {
    place.textContent = "No current readings";
  }

  $("hero-summary").textContent = known
    ? s.advisory?.headline || LEVELS[level].label
    : "No valid readings right now. Take precautions until data is back.";

  const marker = $("scale-marker");
  marker.hidden = !known;
  if (known) marker.style.setProperty("--pos", Math.min(a.aqi, 500) / 5);

  const facts = $("hero-facts");
  facts.replaceChildren();
  if (known && latest) {
    const pm25 = document.createElement("b");
    pm25.textContent = `${latest.pm25} µg/m³`;
    facts.append("PM2.5 ", pm25);
    if (latest.pm10 != null) {
      const pm10 = document.createElement("b");
      pm10.textContent = `${latest.pm10} µg/m³`;
      facts.append(" · PM10 ", pm10);
    }
    facts.append(` · ${TREND_ARROWS[a.trend] ?? ""} ${TREND_WORDS[a.trend] ?? a.trend}`);
  } else {
    facts.textContent = a.reason || "Waiting for valid readings.";
  }
  document.title = `${known ? `AQI ${a.aqi} ${LEVELS[level].label}` : "Data unavailable"} | SmogShield`;
}

// US EPA PM2.5 band tops (µg/m³), used to shade and label the chart
const PM25_BANDS = [
  [9.0, "good"], [35.4, "moderate"], [55.4, "unhealthy_sensitive"],
  [125.4, "unhealthy"], [225.4, "very_unhealthy"], [Infinity, "hazardous"],
];
const SVG_NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}, text) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text != null) node.textContent = text;
  return node;
}

/** A round axis top a little above the highest value: 10, 20, 50, 100, 200, 500… */
function niceMax(value) {
  const target = Math.max(value * 1.2, 10);
  const step = 10 ** Math.floor(Math.log10(target));
  return [1, 2, 2.5, 5, 10].map((m) => m * step).find((n) => n >= target);
}

let lastChart = null;  // what the chart last drew, so it can redraw on resize

function renderChart(s) {
  const a = s.analysis || {};
  const readings = (s.readings || []).filter((r) => typeof r.pm25 === "number");
  const known = levelOf(a) !== "unknown" && readings.length > 0;
  lastChart = known ? { readings, analysis: a } : null;

  const trendChip = $("trend-chip");
  trendChip.hidden = !known;
  if (known) {
    const rate = Math.abs(a.trend_per_hour ?? 0);
    trendChip.dataset.trend = a.trend;
    trendChip.textContent = a.trend === "stable"
      ? "→ Steady"
      : `${TREND_ARROWS[a.trend] ?? ""} ${a.trend === "rising" ? "Rising" : "Falling"} ${rate} µg/m³ per hour`;
  }
  $("spike-chip").hidden = !(known && a.is_spike);

  $("chart").hidden = !known;
  $("chart-empty").hidden = known;
  if (!known) {
    $("chart-empty").textContent = "No valid readings to chart right now.";
    $("chart-summary").textContent = "";
    return;
  }
  drawChart(readings, a);

  const first = readings[0].pm25, last = readings.at(-1).pm25;
  const hours = readings.length > 1 ? ` over ${readings.length} hourly readings` : "";
  $("chart-summary").textContent =
    `PM2.5 went from ${first} to ${last} µg/m³${hours}: ${TREND_WORDS[a.trend] ?? a.trend}` +
    (a.is_spike ? ", with a sudden spike in the latest hour." : ".");
}

/** Draws at the real pixel width, so text stays the same readable size on any screen */
function drawChart(readings, analysis) {
  const chart = $("chart");
  const width = Math.max(chart.parentElement.clientWidth, 280);
  const height = Math.round(Math.min(Math.max(width * 0.42, 220), 380));
  const pad = { left: 52, right: 124, top: 34, bottom: 40 };
  const values = readings.map((r) => r.pm25);
  const top = niceMax(Math.max(...values));
  const plotW = width - pad.left - pad.right, plotH = height - pad.top - pad.bottom;
  const x = (i) => pad.left + (values.length < 2 ? plotW / 2 : (i * plotW) / (values.length - 1));
  const y = (v) => pad.top + plotH * (1 - Math.min(v, top) / top);
  const nodes = [];

  // Level bands behind the line, each labelled on the right (text, not just color)
  let floor = 0;
  for (const [ceiling, level] of PM25_BANDS) {
    if (floor >= top) break;
    const bandTop = Math.min(ceiling, top);
    const h = y(floor) - y(bandTop);
    nodes.push(svg("rect", { x: pad.left, y: y(bandTop), width: plotW, height: h,
                             fill: `var(--${level})`, opacity: 0.22 }));
    if (h >= 16) {
      nodes.push(svg("text", { x: width - pad.right + 28, y: (y(floor) + y(bandTop)) / 2,  // clear of the spike ring
                               "dominant-baseline": "middle", class: "chart__band-label" }, LEVELS[level].label.replace(" for sensitive groups", " (sens.)")));
    }
    floor = ceiling;
  }

  // Y axis: 0 and the top value; X axis: every hour
  nodes.push(svg("text", { x: pad.left - 10, y: y(0), "text-anchor": "end", "dominant-baseline": "middle" }, "0"));
  nodes.push(svg("text", { x: pad.left - 10, y: y(top), "text-anchor": "end", "dominant-baseline": "middle" }, top));
  const hourLabel = (iso) => new Date(iso).toLocaleTimeString([], { hour: "numeric" });  // "8 AM"
  const every = plotW / Math.max(values.length - 1, 1) < 56 ? 2 : 1;  // thin out labels on narrow screens
  readings.forEach((r, i) => {
    if ((values.length - 1 - i) % every === 0) {  // always keep the latest hour
      nodes.push(svg("text", { x: x(i), y: height - 12, "text-anchor": "middle" }, hourLabel(r.timestamp)));
    }
  });

  // Line, points and every value (the spiking point gets its value in the flag instead)
  const spikeAt = analysis.is_spike ? values.length - 1 : -1;
  nodes.push(svg("polyline", { class: "chart__line", points: values.map((v, i) => `${x(i)},${y(v)}`).join(" ") }));
  values.forEach((v, i) => {
    const latest = i === values.length - 1;
    nodes.push(svg("circle", { class: "chart__point", cx: x(i), cy: y(v), r: latest ? 8 : 5 }));
    if (i !== spikeAt) {
      nodes.push(svg("text", { class: "chart__value", x: x(i), y: y(v) - 14, "text-anchor": "middle" }, v));
    }
  });

  // Spike marker on the latest point: a ring plus a flag with the value
  if (spikeAt >= 0) {
    const cx = x(spikeAt), cy = y(values[spikeAt]);
    nodes.push(svg("circle", { cx, cy, r: 16, fill: "none", stroke: "#ffd400", "stroke-width": 5 }));
    nodes.push(svg("circle", { cx, cy, r: 20, fill: "none", stroke: "#000", "stroke-width": 1.5 }));
    const flagW = 104, flagY = Math.max(cy - 56, 2);
    const flagX = Math.min(cx - flagW / 2, width - flagW - 2);
    nodes.push(svg("rect", { x: flagX, y: flagY, width: flagW, height: 24, rx: 6, fill: "#ffd400", stroke: "#000" }));
    nodes.push(svg("text", { x: flagX + flagW / 2, y: flagY + 12, "text-anchor": "middle", "dominant-baseline": "middle",
                             class: "chart__spike-label" }, `SPIKE · ${values[spikeAt]}`));
  }

  chart.setAttribute("viewBox", `0 0 ${width} ${height}`);
  chart.setAttribute("width", width);
  chart.setAttribute("height", height);
  chart.replaceChildren(...nodes);
}

new ResizeObserver(() => {
  if (lastChart) drawChart(lastChart.readings, lastChart.analysis);
}).observe(document.querySelector(".chart"));

/** LIVE badge or the SIMULATED banner, decided by the data's own source field */
function renderMode(s) {
  const latest = s.readings?.at(-1);
  const badge = $("mode-badge");
  if (!latest) {
    badge.dataset.mode = "loading";
    badge.textContent = "No data";
    $("simulated").hidden = true;
    return;
  }
  const simulated = latest.source !== "live";
  badge.dataset.mode = simulated ? "simulated" : "live";
  badge.textContent = simulated ? "Simulated" : "Live";
  $("simulated").hidden = !simulated;
}

function render(s) {
  renderMode(s);
  renderHero(s);
  renderChart(s);
}

function showOffline(error) {
  console.error(error);
  const banner = $("offline");
  banner.hidden = false;
  banner.textContent = lastGood
    ? "Can't reach the SmogShield server. Showing the last data received; retrying…"
    : "Can't reach the SmogShield server yet. Retrying…";
}

// ---------- demo controls (city, scenario, emergency button) ----------

let controlsLoaded = false;

function fillSelect(select, options, current, labelFor) {
  select.replaceChildren(...options.map((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = labelFor(value);
    option.selected = value === current;
    return option;
  }));
}

/** Puts the selects back in sync with what the server really has */
async function loadControls() {
  const [city, scenario] = await Promise.all([getJSON("/api/city"), getJSON("/api/scenario")]);
  fillSelect($("city"), city.options, city.current, (name) => name);
  fillSelect($("scenario"), scenario.options, scenario.current,
             (name) => SCENARIO_LABELS[name] ?? name.replaceAll("_", " "));
  controlsLoaded = true;
  setControlsBusy(false);
}

function setControlsBusy(busy) {
  for (const id of ["city", "scenario", "emergency"]) $(id).disabled = busy || !controlsLoaded;
}

function setControlStatus(text, tone = "") {
  $("control-status").textContent = text;
  $("control-status").dataset.tone = tone;
}

/** POSTs a control change, then refreshes everything right away */
async function changeControl(url, busyText, doneText) {
  setControlsBusy(true);
  setControlStatus(busyText);
  try {
    await getJSON(url, { method: "POST" });
    setControlStatus(doneText);
    poll();
  } catch (error) {
    console.error(error);
    setControlStatus("Couldn't change that setting. Is the server running?", "error");
  } finally {
    try { await loadControls(); } catch { setControlsBusy(false); }
  }
}

$("city").addEventListener("change", (event) => {
  const city = event.target.value;
  changeControl(`/api/city/${encodeURIComponent(city)}`, `Switching to ${city}…`, `Now showing ${city}.`);
});

$("scenario").addEventListener("change", (event) => {
  const name = event.target.value;
  const label = SCENARIO_LABELS[name] ?? name;
  changeControl(`/api/scenario/${encodeURIComponent(name)}`, `Switching to “${label}”…`,
                name === "live" ? "Back to live data." : `Demo scenario: ${label} (simulated).`);
});

$("emergency").addEventListener("click", () => {
  changeControl("/api/scenario/hazardous", "Triggering a simulated smog emergency…",
                "Smog emergency triggered (simulated data).");
});

// ---------- polling ----------

let pollTimer = null;
let polling = false;
let pollAgain = false;

/** One refresh. Safe to call any time: overlapping calls are merged, never stacked */
async function poll() {
  if (polling) {
    pollAgain = true;
    return;
  }
  polling = true;
  clearTimeout(pollTimer);
  try {
    const s = await getJSON("/api/status");
    render(s);
    lastGood = s;
    $("offline").hidden = true;
    if (!controlsLoaded) loadControls().catch(console.error);
  } catch (error) {
    showOffline(error);  // keep whatever is on screen
  } finally {
    polling = false;
    if (pollAgain) {
      pollAgain = false;
      poll();
    } else {
      pollTimer = setTimeout(poll, POLL_MS);  // a chain, not setInterval: slow polls never pile up
    }
  }
}

loadControls().catch((error) => {
  console.error(error);
  setControlStatus("Demo controls unavailable until the server responds.", "error");
});
poll();
