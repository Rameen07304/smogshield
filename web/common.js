// Shared by every SmogShield page (load before the page's own script).
// Top-level consts in classic scripts are visible to the scripts loaded after this one.
"use strict";

const POLL_MS = 5000;          // every page polls /api/status this often; live data is cached for 10 min
const REQUEST_TIMEOUT_MS = 15000;

const LEVELS = {
  good:                { label: "Good" },
  satisfactory:        { label: "Satisfactory" },
  moderate:            { label: "Moderate" },
  poor:                { label: "Poor" },
  very_poor:           { label: "Very Poor" },
  severe:              { label: "Severe" },
  unknown:             { label: "Data unavailable" },
};
const TREND_WORDS = { rising: "rising", falling: "falling", stable: "steady" };

const $ = (id) => document.getElementById(id);

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
