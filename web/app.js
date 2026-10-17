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

function render(s) {
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

// ---------- polling ----------

async function poll() {
  try {
    const s = await getJSON("/api/status");
    render(s);
    lastGood = s;
    $("offline").hidden = true;
  } catch (error) {
    showOffline(error);  // keep whatever is on screen
  } finally {
    setTimeout(poll, POLL_MS);  // a chain, not setInterval: slow polls never pile up
  }
}

poll();
