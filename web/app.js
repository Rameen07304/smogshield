// SmogShield dashboard (Screen 1): polls /api/status and renders each panel.
// Rules: textContent only (never inject API data as HTML), keep the last good data on screen
// when a poll fails, and never leave a panel blank.
// Needs common.js first (POLL_MS, LEVELS, $, getJSON, localTime, levelOf, and the language helpers t,
// levelLabel, trendWord, cityName, LANG). Every visible string goes through t() so the site works in Urdu.
"use strict";

const SCENARIO_LABELS = {
  live: "Live data",
  good: "Good",
  satisfactory: "Satisfactory",
  moderate: "Moderate",
  poor: "Poor",
  very_poor: "Very Poor",
  severe: "Severe",
  spike: "Spike: smog builds, then clears",
};

let lastGood = null;  // the last /api/status that rendered fine

// ---------- panels ----------

function renderHero(s) {
  const a = s.analysis || {};
  const level = levelOf(a);
  const known = level !== "unknown";
  const latest = s.readings?.at(-1);

  $("hero").dataset.level = level;
  $("hero-aqi").textContent = known && a.aqi != null ? a.aqi : "—";
  $("hero-category").textContent = levelLabel(level);

  const place = $("hero-place");
  place.replaceChildren();
  if (latest) {
    const city = document.createElement("strong");
    city.textContent = cityName(latest.location);
    place.append(city, ` · ${t("reading for {time}", { time: localTime(latest.timestamp) })}`);
  } else {
    place.textContent = t("No current readings");
  }

  $("hero-summary").textContent = known
    ? adviceInLanguage(s.advisory).headline || levelLabel(level)
    : t("No valid readings right now. Take precautions until data is back.");

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
    facts.append(` · ${trendWord(a.trend)}`);
    if (a.dominant_pollutant === "pm10") facts.append(` · ${t("AQI driven by PM10")}`);
    const over = targetNote(latest);
    if (over) {
      const note = document.createElement("small");
      note.className = "hero__target";
      note.textContent = over;
      facts.append(note);
    }
  } else {
    facts.textContent = (LANG === "en" && a.reason) || t("Waiting for valid readings.");
  }
  document.title = `${known ? `${t("AQI")} ${a.aqi} ${levelLabel(level)}` : levelLabel("unknown")} | SmogShield`;
}

/** "PM2.5 is 2.4× the national 24-hour target" when a pollutant is above its NCAP target, else "" */
function targetNote(latest) {
  const parts = [];
  for (const [key, name] of [["pm25", "PM2.5"], ["pm10", "PM10"]]) {
    const value = latest[key], target = NATIONAL_TARGETS[key];
    if (typeof value === "number" && value > target) {
      parts.push(t("{name} is {x}× the national 24-hour target ({target} µg/m³)",
                   { name, x: (value / target).toFixed(1), target }));
    }
  }
  return parts.length ? `${parts.join("; ")}. ${t("Hourly value vs a 24-hour target.")}` : "";
}

// PM2.5 band tops (µg/m³) for the NCAP categories under US EPA AQI math, drawn as threshold lines on the chart.
// Must match agents/analysis.py: AQI 200 = 125.4, 300 = 225.4, 400 = 275.4.
const PM25_BANDS = [
  [9.0, "good"], [35.4, "satisfactory"], [125.4, "moderate"],
  [225.4, "poor"], [275.4, "very_poor"], [Infinity, "severe"],
];
// NCAP 2023 Table 2: national 24-hour targets (µg/m³). We compare them with an hourly value.
const NATIONAL_TARGETS = { pm25: 75, pm10: 150 };
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
      ? t("Steady")
      : t(a.trend === "rising" ? "Rising {rate} µg/m³ per hour" : "Falling {rate} µg/m³ per hour", { rate });
  }
  $("spike-chip").hidden = !(known && a.is_spike);

  $("chart").toggleAttribute("hidden", !known);  // <svg> has no .hidden property, so set the attribute
  $("chart-empty").hidden = known;
  if (!known) {
    $("chart-empty").textContent = t("No valid readings to chart right now.");
    $("chart-summary").textContent = "";
    return;
  }
  drawChart(readings, a);

  const first = readings[0].pm25, last = readings.at(-1).pm25;
  $("chart-summary").textContent =
    t("PM2.5 went from {first} to {last} µg/m³ over {n} hourly readings: {trend}",
      { first, last, n: readings.length, trend: trendWord(a.trend) }) +
    (a.is_spike ? `, ${t("with a sudden spike in the latest hour")}.` : ".");
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

  // Category thresholds as hairlines, each band named on the right (the level colour lives in the hero only)
  let floor = 0;
  for (const [ceiling, level] of PM25_BANDS) {
    if (floor >= top) break;
    const bandTop = Math.min(ceiling, top);
    const h = y(floor) - y(bandTop);
    if (ceiling < top) {
      nodes.push(svg("line", { class: "chart__threshold", x1: pad.left, x2: pad.left + plotW, y1: y(ceiling), y2: y(ceiling) }));
    }
    if (h >= 16) {
      nodes.push(svg("text", { x: width - pad.right + 28, y: (y(floor) + y(bandTop)) / 2,  // clear of the spike ring
                               "dominant-baseline": "middle", class: "chart__band-label" }, levelLabel(level)));
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
    nodes.push(svg("circle", { class: "chart__spike-ring", cx, cy, r: 14 }));
    const flagW = 104, flagY = Math.max(cy - 52, 2);
    const flagX = Math.min(cx - flagW / 2, width - flagW - 2);
    nodes.push(svg("rect", { class: "chart__spike-flag", x: flagX, y: flagY, width: flagW, height: 24, rx: 3 }));
    nodes.push(svg("text", { x: flagX + flagW / 2, y: flagY + 12, "text-anchor": "middle", "dominant-baseline": "middle",
                             class: "chart__spike-label" }, t("Spike · {v}", { v: values[spikeAt] })));
  }

  chart.setAttribute("viewBox", `0 0 ${width} ${height}`);
  chart.setAttribute("width", width);
  chart.setAttribute("height", height);
  chart.replaceChildren(...nodes);
}

new ResizeObserver(() => {
  if (lastChart) drawChart(lastChart.readings, lastChart.analysis);
}).observe(document.querySelector(".chart"));

// ---------- advisory ----------

const AUDIENCES = ["general", "children", "elderly", "respiratory_heart", "outdoor_workers"];

/** The advisory in the site language: the backend sends English plus an Urdu version (adv.urdu) */
function adviceInLanguage(adv = {}) {
  if (LANG !== "ur" || !adv.urdu) return adv;
  return { ...adv.urdu, audiences: adv.urdu.audiences ?? { general: adv.urdu.actions } };
}

function fillList(id, items, emptyText) {
  const list = $(id);
  const lines = (items || []).filter((line) => typeof line === "string" && line.trim());
  list.replaceChildren(...(lines.length ? lines : [emptyText]).map((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    return li;
  }));
}

function renderAdvisory(s) {
  const adv = adviceInLanguage(s.advisory || {});
  $("advice-headline").textContent = adv.headline || t("Advice is unavailable right now. Take care outdoors.");
  $("advice-note").textContent = adv.time_note || "";
  $("advice-note").hidden = !adv.time_note;
  $("advice-forecast").textContent = adv.forecast_note || "";
  $("advice-forecast").hidden = !adv.forecast_note;
  for (const who of AUDIENCES) {
    const items = adv.audiences?.[who] ?? (who === "general" ? adv.actions : []);
    fillList(`aud-${who}`, items, t("No specific advice for this group right now."));
  }
  $("advice-disclaimer").textContent = adv.disclaimer || t("General guidance, not medical advice.");
}

// ---------- alert feed ----------

const FEED_LIMIT = 20;
const SIM_PREFIX = "[SIMULATION] ";
const SEVERITY = {  // the shape beside each word is drawn in CSS, so colour is never the only cue
  info: { label: "Info" },
  warning: { label: "Warning" },
  critical: { label: "Critical" },
};
let lastFeed = null;
const feedItems = new Map();  // alert key -> <li>, so existing items are updated, never re-created
let feedLoaded = false;

const alertKey = (a) => `${a.created_at}|${a.location}|${a.level}|${a.message}`;

function deliveryText(a) {
  if (a.status === "queued") return t("Sending to Telegram…");
  if (a.status === "sent") return t(a.channel === "telegram" ? "Sent via Telegram" : "Dashboard feed");
  return t("Telegram failed, kept in the feed");
}

function buildAlertItem(a) {
  const simulated = a.message.startsWith(SIM_PREFIX);
  const sev = SEVERITY[a.severity] ?? SEVERITY.warning;
  const li = document.createElement("li");
  li.className = "alert-item";
  li.dataset.severity = a.severity in SEVERITY ? a.severity : "warning";
  if (simulated) li.dataset.simulated = "";

  const top = document.createElement("div");
  top.className = "alert-item__top";
  const badge = document.createElement("span");
  badge.className = "sev-badge";
  badge.textContent = t(sev.label);
  top.append(badge);
  if (simulated) {
    const tag = document.createElement("span");
    tag.className = "sim-tag";
    tag.textContent = t("Simulated");
    top.append(tag);
  }
  const message = document.createElement("p");
  message.className = "alert-item__message";
  message.dir = "auto";  // an English message keeps left-to-right order inside the Urdu page
  message.textContent = alertText(a);
  const meta = document.createElement("p");
  meta.className = "alert-item__meta";
  li.append(top, message, meta);
  updateAlertItem(li, a);
  return li;
}

/** The alert message in the site language, without the [SIMULATION] prefix (shown as a tag instead) */
function alertText(a) {
  const text = (LANG === "ur" && a.message_ur) || a.message;
  return text.startsWith(SIM_PREFIX) ? text.slice(SIM_PREFIX.length) : text;
}

function updateAlertItem(li, a) {
  li.querySelector(".alert-item__meta").textContent = `${localTime(a.created_at)} · ${deliveryText(a)}`;
}

function renderFeed(feed) {
  const list = $("feed");
  const keys = feed.map(alertKey);
  // Drop items that are no longer in the feed
  for (const [key, li] of feedItems) {
    if (!keys.includes(key)) {
      li.remove();
      feedItems.delete(key);
    }
  }
  // Add new ones at the top (oldest of the new first, so the newest ends up on top); update the rest
  const fresh = [];
  for (let i = feed.length - 1; i >= 0; i--) {
    const a = feed[i], key = keys[i];
    const existing = feedItems.get(key);
    if (existing) {
      updateAlertItem(existing, a);
      continue;
    }
    const li = buildAlertItem(a);
    if (feedLoaded) {
      li.classList.add("is-new");  // animate only alerts that arrive while the page is open
      fresh.push(a);
    }
    list.prepend(li);
    feedItems.set(key, li);
  }

  $("feed-empty").hidden = feed.length > 0;
  $("feed-empty").textContent = t("No alerts yet. They appear here when air quality crosses a threshold or spikes.");
  $("feed-count").hidden = feed.length === 0;
  $("feed-count").textContent = feed.length === 1 ? t("1 alert") : t("{n} alerts", { n: feed.length });
  $("feed-error").hidden = true;
  if (fresh.length) {
    $("announcer").textContent = fresh.reverse()
      .map((a) => t("{sev} alert: {msg}", { sev: t(SEVERITY[a.severity]?.label ?? a.severity), msg: alertText(a) })).join(" ");
  }
  feedLoaded = true;
}

async function refreshFeed() {
  try {
    lastFeed = await getJSON(`/api/alerts?limit=${FEED_LIMIT}`);
    renderFeed(lastFeed);
  } catch (error) {
    console.error(error);
    $("feed-error").hidden = !feedLoaded;  // before the first load, the "Loading…" text stays
  }
}

// ---------- pipeline strip ----------

const STEPS = ["monitor", "forecast", "analysis", "advisory", "alert"];  // graph order (graph.py)
const STEP_MS = 220;  // how long each row stays "working" before its check lands
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
let flowTimers = [];

function pipelineOutputs(s) {
  const readings = s.readings || [];
  const latest = readings.at(-1);
  const a = s.analysis || {};
  const level = levelOf(a);
  const alerts = s.alerts || [];
  return {
    monitor: latest
      ? `${t("{n} hourly readings", { n: readings.length })} · ${t(latest.source === "live" ? "live" : "simulated")}`
      : t("No readings"),
    forecast: forecastOutput(s.forecast),
    analysis: level === "unknown"
      ? t("No valid readings")
      : `${t("AQI")} ${a.aqi} · ${trendWord(a.trend)}${a.is_spike ? ` · ${t("spike!")}` : ""}`,
    advisory: t(s.advisory?.audiences ? "Advice for 5 groups + Urdu" : "Cautious default advice"),
    alert: alerts.length
      ? t("{sev} alert raised", { sev: t(SEVERITY[alerts[0].severity]?.label ?? alerts[0].severity) })
      : t(level === "unknown" ? "No alert without data" : "No new alert"),
  };
}

/** "Next 6 h: peaks Poor (AQI 236)" from the forecast agent's summary, or why there is none */
function forecastOutput(f) {
  const six = f?.next_6h;
  if (!six) return t("No forecast available");
  return t("Next 6 h peaks {level} (AQI {aqi})", { level: levelLabel(six.peak_level), aqi: six.peak_aqi }) +
    (f.source === "live" ? "" : ` · ${t("simulated")}`);
}

let lastOutputs = "";  // the confirm sequence replays only when an agent's output actually changed

function renderPipeline(s) {
  const outputs = pipelineOutputs(s);
  const key = STEPS.map((step) => outputs[step]).join("|");
  const changed = key !== lastOutputs;
  lastOutputs = key;
  for (const step of STEPS) $(`out-${step}`).textContent = outputs[step];
  const at = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  $("pipeline-run").dataset.at = at;
  $("pipeline-run").textContent = t("Last run {at} · refreshes every {s} s", { at, s: POLL_MS / 1000 });

  // Light the nodes up one after another, then leave them all "done"
  flowTimers.forEach(clearTimeout);
  flowTimers = [];
  const nodes = STEPS.map((step) => document.querySelector(`.node[data-step="${step}"]`));
  if (reducedMotion.matches || !changed) {
    nodes.forEach((node) => { node.dataset.state = "done"; });
    return;
  }
  nodes.forEach((node) => { node.dataset.state = ""; });
  nodes.forEach((node, i) => {
    flowTimers.push(setTimeout(() => { node.dataset.state = "active"; }, i * STEP_MS));
    flowTimers.push(setTimeout(() => { node.dataset.state = "done"; }, (i + 1) * STEP_MS));
  });
}

function pipelineOffline() {
  flowTimers.forEach(clearTimeout);
  for (const node of document.querySelectorAll(".node")) node.dataset.state = "error";
  lastOutputs = "";  // replay the sequence when the server comes back
  $("pipeline-run").textContent = t("Pipeline unreachable: waiting for the server…");
}

/** LIVE badge or the SIMULATED banner, decided by the data's own source field */
function renderMode(s) {
  const latest = s.readings?.at(-1);
  const badge = $("mode-badge");
  if (!latest) {
    badge.dataset.mode = "loading";
    badge.textContent = t("No data");
    $("simulated").hidden = true;
    return;
  }
  const simulated = latest.source !== "live";
  badge.dataset.mode = simulated ? "simulated" : "live";
  badge.textContent = t(simulated ? "Simulated" : "Live");
  $("simulated").hidden = !simulated;
  // Explain why: a chosen demo scenario, or live data failing and the backend falling back to mock
  const liveChosen = controlsLoaded && $("scenario").value === "live";
  $("simulated-why").textContent = t(liveChosen
    ? "Live data is unavailable right now, so these are simulated readings, not real air quality."
    : "Demo scenario: these are not real air quality readings.");
}

function render(s) {
  renderMode(s);
  renderHero(s);
  renderPipeline(s);
  renderChart(s);
  renderAdvisory(s);
}

function showOffline(error) {
  console.error(error);
  pipelineOffline();
  $("mode-badge").dataset.mode = "offline";  // never claim LIVE while we can't reach the server
  $("mode-badge").textContent = t("Offline");
  const banner = $("offline");
  banner.hidden = false;
  if (lastGood) {
    // Keep every panel as it was: stale data is far more useful on stage than an empty screen
    banner.textContent = t("Can't reach the SmogShield server. Showing data from {at}; retrying…",
                           { at: $("pipeline-run").dataset.at || t("the last refresh") });
    return;
  }
  banner.textContent = t("Can't reach the SmogShield server yet. Retrying every few seconds…");
  // Nothing received yet: say so in each panel instead of "Loading…" forever
  $("hero-category").textContent = t("Not connected");
  $("hero-place").textContent = t("Waiting for the server");
  $("hero-summary").textContent = t("Start it with: uvicorn app:app");
  $("chart-empty").textContent = t("The chart appears once the server responds.");
  $("advice-headline").textContent = t("Advice appears once the server responds.");
  for (const who of AUDIENCES) fillList(`aud-${who}`, [], t("Waiting for the server…"));
  if (!feedLoaded) $("feed-empty").textContent = t("Alerts appear once the server responds.");
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
  CITY_UR = city.labels_ur || CITY_UR;
  fillSelect($("city"), city.options, city.current, cityName);
  fillSelect($("scenario"), scenario.options, scenario.current,
             (name) => t(SCENARIO_LABELS[name] ?? name.replaceAll("_", " ")));
  controlsLoaded = true;
  setControlsBusy(false);
}

function setControlsBusy(busy) {
  for (const id of ["city", "scenario", "emergency"]) $(id).disabled = busy || !controlsLoaded;
}

let statusTimer = null;
function setControlStatus(text, tone = "") {
  $("control-status").textContent = text;
  $("control-status").dataset.tone = tone;
  clearTimeout(statusTimer);
  if (text && tone !== "error" && !text.endsWith("…")) {
    statusTimer = setTimeout(() => setControlStatus(""), 8000);  // confirmations fade; errors and "working…" stay
  }
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
    setControlStatus(t("Couldn't change that setting. Is the server running?"), "error");
  } finally {
    try { await loadControls(); } catch { setControlsBusy(false); }
  }
}

$("city").addEventListener("change", (event) => {
  const city = event.target.value;
  changeControl(`/api/city/${encodeURIComponent(city)}`, t("Switching to {city}…", { city: cityName(city) }),
                t("Now showing {city}.", { city: cityName(city) }));
});

$("scenario").addEventListener("change", (event) => {
  const name = event.target.value;
  const label = t(SCENARIO_LABELS[name] ?? name);
  changeControl(`/api/scenario/${encodeURIComponent(name)}`, t("Switching to “{label}”…", { label }),
                name === "live" ? t("Back to live data.") : t("Demo scenario: {label} (simulated).", { label }));
});

$("emergency").addEventListener("click", () => {
  changeControl("/api/scenario/severe", t("Triggering a simulated smog emergency…"),
                t("Smog emergency triggered (simulated data)."));
});

// ---------- Ask SmogShield (one question, answered from the current reading) ----------

$("ask").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = $("ask-input").value.trim();
  if (!question) return;
  const answer = $("ask-answer");
  answer.hidden = false;
  answer.dataset.state = "loading";
  answer.textContent = t("Thinking…");  // textContent only: the answer comes from an AI model
  $("ask-input").disabled = $("ask-button").disabled = true;
  try {
    const reply = await getJSON("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    answer.dataset.state = reply.source === "ai" ? "" : "note";  // off / busy / unsure: calm, not an error
    answer.textContent = reply.answer;
  } catch (error) {
    console.error(error);
    answer.dataset.state = "error";
    answer.textContent = t("Couldn't reach SmogShield. The advice above still applies.");
  } finally {
    $("ask-input").disabled = $("ask-button").disabled = false;
    $("ask-input").focus();
  }
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
    const s = await getJSON("/api/status");  // runs the pipeline, which may add an alert…
    render(s);
    lastGood = s;
    $("offline").hidden = true;
    await refreshFeed();                     // …so read the feed afterwards
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

// Switching language re-renders the last data at once (no reload, no new pipeline run)
document.addEventListener("languagechange", () => {
  if (lastGood) render(lastGood);
  if (lastFeed) {  // rebuild the items in the new language, without "new alert" animation or announcement
    $("feed").replaceChildren();
    feedItems.clear();
    feedLoaded = false;
    renderFeed(lastFeed);
  }
  if (controlsLoaded) loadControls().catch(console.error);
});

loadControls().catch((error) => {
  console.error(error);
  setControlStatus(t("Demo controls unavailable until the server responds."), "error");
});
poll();
