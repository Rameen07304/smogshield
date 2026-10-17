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
