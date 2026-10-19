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
const STALE_HOURS = 2;  // a live reading older than this gets a "may be delayed" note (the source updates hourly)

// ---------- panels ----------

/** The plain answer at the top of the page, for each level */
const OUTSIDE = {
  good: "Yes. The air is clean today.",
  satisfactory: "Yes. People with asthma or heart problems should take it easy.",
  moderate: "Yes, for short times. Children, older people and the sick should avoid long or hard exercise outside.",
  poor: "Only if you need to. Children, older people and the sick should stay indoors.",
  very_poor: "Stay indoors if you can. If you must go out, wear an N95 mask.",
  severe: "No. Stay indoors with windows closed. Go out only if you must, with an N95 mask.",
  unknown: "We can't tell right now. Be careful outdoors until the data is back.",
};

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

  $("hero-answer").textContent = t(OUTSIDE[level] ?? OUTSIDE.unknown);

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
    const age = Math.floor((Date.now() - Date.parse(latest.timestamp)) / 3.6e6);
    if (latest.source === "live" && age >= STALE_HOURS) {
      const stale = document.createElement("small");
      stale.className = "hero__stale";
      stale.textContent = t("Data may be delayed: the latest reading is {h} hours old.", { h: age });
      facts.append(stale);
    }
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

const drawn = new Map();  // svg id -> [points, options] it last drew, so both charts redraw on resize
const hourLabel = (iso) => new Date(iso).toLocaleTimeString([], { ...PKT, hour: "numeric" });  // "8 AM"

function renderChart(s) {
  const a = s.analysis || {};
  const readings = (s.readings || []).filter((r) => typeof r.pm25 === "number");
  const known = levelOf(a) !== "unknown" && readings.length > 0;

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
    drawn.delete("chart");
    $("chart-empty").textContent = t("No valid readings to chart right now.");
    $("chart-summary").textContent = "";
    return;
  }
  // Every value labelled, the latest hour emphasised, a spike flagged on the latest point
  drawSeries("chart", readings.map((r) => ({ label: hourLabel(r.timestamp), value: r.pm25 })),
             { emphasis: readings.length - 1, spikeAt: a.is_spike ? readings.length - 1 : -1 });

  const first = readings[0].pm25, last = readings.at(-1).pm25;
  $("chart-summary").textContent =
    t("PM2.5 went from {first} to {last} µg/m³ over {n} hourly readings: {trend}",
      { first, last, n: readings.length, trend: trendWord(a.trend) }) +
    (a.is_spike ? `, ${t("with a sudden spike in the latest hour")}.` : ".");
}

/** The next 24 hours from the forecast agent, the best time to go out, and the coming days */
function renderForecast(s) {
  const f = s.forecast || {};
  const hours = (f.hourly || []).filter((p) => typeof p.pm25 === "number");
  const known = hours.length > 1;
  $("forecast-chart").toggleAttribute("hidden", !known);
  $("forecast-empty").hidden = known;
  $("forecast-source").hidden = !known || f.source === "live";
  if (!known) {
    drawn.delete("forecast-chart");
    $("forecast-empty").textContent = t("No forecast available right now.");
    $("forecast-summary").textContent = "";
    $("best-chip").hidden = true;
    $("outlook").replaceChildren();
    $("school").hidden = true;
    return;
  }

  // Best ~2-hour window to go outside, shaded on the chart (end is exclusive)
  const best = f.best_time;
  const from = best ? hours.findIndex((p) => Date.parse(p.time) === Date.parse(best.start)) : -1;
  const to = from >= 0 ? Math.min(from + Math.round((Date.parse(best.end) - Date.parse(best.start)) / 3.6e6) - 1, hours.length - 1) : -1;
  $("best-chip").hidden = from < 0;
  if (from >= 0) $("best-chip").textContent = t("Best time outside: {from}–{to}", { from: localTime(best.start), to: localTime(best.end) });

  const values = hours.map((p) => p.pm25);
  const peak = values.indexOf(Math.max(...values));
  drawSeries("forecast-chart", hours.map((p) => ({ label: hourLabel(p.time), value: Math.round(p.pm25) })), {
    emphasis: 0, valuesAt: [0, peak], labelFromStart: true,
    highlight: from >= 0 ? { from, to, label: t("Best time") } : null,
  });
  $("forecast-summary").textContent = t("Peaks at {level} (AQI {aqi}) around {time}. A model estimate: most reliable for the next 6 hours.", {
    level: levelLabel(hours[peak].level), aqi: hours[peak].aqi, time: localTime(hours[peak].time),
  });

  // Coming days: the worst hour of each day
  const dayName = (date) => new Date(`${date}T12:00:00+05:00`).toLocaleDateString(LANG === "ur" ? "ur" : [], { ...PKT, weekday: "long" });
  $("outlook").replaceChildren(...(f.outlook || []).slice(0, 4).map((day, i) => {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.className = "outlook__day";
    name.textContent = i === 0 ? t("Today") : dayName(day.date);
    const tag = document.createElement("span");
    tag.className = "level-tag";
    tag.dataset.level = day.peak_level in LEVELS ? day.peak_level : "unknown";
    tag.textContent = levelLabel(day.peak_level);
    const aqi = document.createElement("span");
    aqi.className = "outlook__aqi";
    aqi.textContent = t("peak AQI {aqi}", { aqi: day.peak_aqi });
    li.append(name, tag, aqi);
    return li;
  }));
  renderSchoolDay(f.school_day, dayName);
}

/** What schools should plan for the next school day, from its worst school-hours forecast */
const SCHOOL_ADVICE = {
  good: "A normal school day.",
  satisfactory: "A normal school day. Children with asthma should keep their inhalers with them.",
  moderate: "School as normal, but shorten long or intense outdoor PE and sports.",
  poor: "Open, but move PE, sports and the morning assembly indoors, and keep windows closed.",
  very_poor: "All activities indoors. Pupils with asthma or heart conditions may be safer at home.",
  severe: "Emergency air. Closing schools or moving classes online is advisable.",
};

function renderSchoolDay(day, dayName) {
  $("school").hidden = !day || !(day.peak_level in SCHOOL_ADVICE);
  if ($("school").hidden) return;
  const tomorrow = new Date(Date.now() + 864e5).toLocaleDateString("en-CA", PKT);  // YYYY-MM-DD in Pakistan
  $("school-day").textContent = day.date === tomorrow ? t("Schools tomorrow?") : t("Schools on {day}?", { day: dayName(day.date) });
  $("school-level").dataset.level = day.peak_level;
  $("school-level").textContent = levelLabel(day.peak_level);
  $("school-level").title = t("peak AQI {aqi}", { aqi: day.peak_aqi });
  $("school-advice").textContent = t(SCHOOL_ADVICE[day.peak_level]);
}

/**
 * One line chart for both the recent readings and the forecast, drawn at the real pixel width so text
 * stays the same readable size on any screen. points: [{label, value}].
 * options: emphasis (index drawn larger), spikeAt (index flagged), valuesAt (indexes to label, default all),
 * labelFromStart (thin hour labels from the first point instead of the last), highlight {from, to, label}.
 */
function drawSeries(id, points, options = {}) {
  drawn.set(id, [points, options]);
  const { emphasis = -1, spikeAt = -1, valuesAt = null, labelFromStart = false, highlight = null } = options;
  const chart = $(id);
  const width = Math.max(chart.parentElement.clientWidth, 280);
  const height = Math.round(Math.min(Math.max(width * 0.42, 220), 380));
  const pad = { left: 52, right: 124, top: 34, bottom: 40 };
  const values = points.map((p) => p.value);
  const top = niceMax(Math.max(...values));
  const plotW = width - pad.left - pad.right, plotH = height - pad.top - pad.bottom;
  const x = (i) => pad.left + (values.length < 2 ? plotW / 2 : (i * plotW) / (values.length - 1));
  const y = (v) => pad.top + plotH * (1 - Math.min(v, top) / top);
  const step = plotW / Math.max(values.length - 1, 1);
  const nodes = [];

  // Highlighted window (best time to go out), behind everything else
  if (highlight) {
    const x1 = x(highlight.from) - step / 2, x2 = x(highlight.to) + step / 2;
    nodes.push(svg("rect", { class: "chart__best", x: Math.max(x1, pad.left), y: pad.top,
                             width: Math.min(x2, pad.left + plotW) - Math.max(x1, pad.left), height: plotH }));
    nodes.push(svg("text", { class: "chart__best-label", x: (x1 + x2) / 2, y: pad.top - 10, "text-anchor": "middle" }, highlight.label));
  }

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

  // Y axis: 0 and the top value; X axis: hour labels, thinned so they never collide
  nodes.push(svg("text", { x: pad.left - 10, y: y(0), "text-anchor": "end", "dominant-baseline": "middle" }, "0"));
  nodes.push(svg("text", { x: pad.left - 10, y: y(top), "text-anchor": "end", "dominant-baseline": "middle" }, top));
  const every = Math.max(1, Math.ceil(56 / step));
  points.forEach((p, i) => {
    if ((labelFromStart ? i : values.length - 1 - i) % every === 0) {
      nodes.push(svg("text", { x: x(i), y: height - 12, "text-anchor": "middle" }, p.label));
    }
  });

  // Line, points and values (the spiking point gets its value in the flag instead)
  const dense = values.length > 12;
  nodes.push(svg("polyline", { class: "chart__line", points: values.map((v, i) => `${x(i)},${y(v)}`).join(" ") }));
  values.forEach((v, i) => {
    nodes.push(svg("circle", { class: "chart__point", cx: x(i), cy: y(v), r: i === emphasis ? 8 : dense ? 3 : 5 }));
    if (i !== spikeAt && (!valuesAt || valuesAt.includes(i))) {
      nodes.push(svg("text", { class: "chart__value", x: x(i), y: y(v) - 14, "text-anchor": "middle" }, v));
    }
  });

  // Spike marker: a ring plus a flag with the value
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

const redraw = new ResizeObserver(() => {
  for (const [id, [points, options]] of drawn) drawSeries(id, points, options);
});
for (const figure of document.querySelectorAll(".chart")) redraw.observe(figure);

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
  // Say who wrote the advice: the Urdu version is always the vetted rule-based text
  const model = LANG === "ur" ? "" : s.advisory?.ai_model;
  $("advice-source").hidden = !s.advisory;
  $("advice-source").toggleAttribute("data-ai", Boolean(model));
  const message = shareText(s, adv);
  $("share-wa").hidden = !message;
  if (message) $("share-wa").href = `https://wa.me/?text=${encodeURIComponent(message)}`;
  $("read-aloud").hidden = !("speechSynthesis" in window) || !adv.headline;
  $("advice-source").textContent = model
    ? t("Advice written by AI ({model} on Groq), checked against the NCAP categories.", { model: shortModel(model) })
    : t("Advice from SmogShield's NCAP rules.");
}

/** Today's advice as a WhatsApp message in the site language; simulated data is always marked */
function shareText(s, adv) {
  const latest = s.readings?.at(-1), a = s.analysis;
  if (!latest || !a?.aqi || !adv.headline) return "";
  const list = (lines) => (lines || []).slice(0, 3).map((line) => `• ${line}`);
  return [
    latest.source === "live" ? "" : `[${t("Simulated")}]`,
    `SmogShield: ${cityName(latest.location)}${LANG === "ur" ? "،" : ","} ${levelLabel(a.level)} (${t("AQI")} ${a.aqi})`,
    adv.headline,
    ...list(adv.audiences?.general),
    `${t("Children & schools")}:`, ...list(adv.audiences?.children).slice(0, 2),
    adv.disclaimer,
  ].filter(Boolean).join("\n");
}

/** Read the advice aloud with the browser's own speech. Urdu needs an Urdu voice on the device;
 *  without one it reads the English advice instead of mispronouncing Urdu with an English voice. */
$("read-aloud").addEventListener("click", () => {
  const button = $("read-aloud");
  if (speechSynthesis.speaking) { speechSynthesis.cancel(); return; }
  const s = lastGood || {};
  const urduVoice = speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith("ur"));
  const useUrdu = LANG === "ur" && urduVoice;
  // The plain answers first, then the advice for everyone. Without an Urdu voice it reads the English
  // version, since an English voice can't pronounce Urdu script.
  const say = useUrdu ? t : (text) => text;
  const adv = useUrdu ? adviceInLanguage(s.advisory) : (s.advisory || {});
  const level = levelOf(s.analysis || {});
  const school = s.forecast?.school_day;
  const text = [
    say("Can I go outside?"), say(OUTSIDE[level] ?? OUTSIDE.unknown),
    school?.peak_level in SCHOOL_ADVICE ? `${say("Schools tomorrow?")} ${say(SCHOOL_ADVICE[school.peak_level])}` : "",
    adv.headline, ...(adv.audiences?.general || []),
  ].filter(Boolean).join(" ");
  const speech = new SpeechSynthesisUtterance(text);
  speech.lang = useUrdu ? urduVoice.lang : "en-US";
  if (useUrdu) speech.voice = urduVoice;
  speech.rate = 0.95;
  speech.onstart = () => {  // no Urdu voice on this device: say so, since it reads the English advice
    button.textContent = LANG === "ur" && !urduVoice ? t("Stop (reading in English: no Urdu voice)") : t("Stop reading");
  };
  speech.onend = speech.onerror = () => { button.textContent = t("Read aloud"); };
  speechSynthesis.speak(speech);
});

/** "openai/gpt-oss-20b" -> "gpt-oss-20b" */
const shortModel = (model) => model.split("/").pop();

// ---------- alert feed ----------

// The dashboard shows only alerts that need attention now; History has every one
const FEED_LIMIT = 100;  // everything the alert store keeps, filtered below
const ACTIVE_HOURS = 3;  // same as the alert agent's memory (ALERT_MEMORY_HOURS): it re-alerts after this
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

const LEVEL_RANK = Object.keys(LEVELS).filter((level) => level !== "unknown");  // good ... severe
const rankOf = (level) => LEVEL_RANK.indexOf(level);

/** What needs attention now, at most two alerts, newest first. Candidates: the city on screen, the last few
 *  hours, warning or critical (Poor or worse, now or forecast) or a sudden spike, and the same live or
 *  simulated data as the dashboard. Of those, the newest one about conditions now, while the air is still
 *  Poor or worse (or it was a spike), and the newest forecast warning, while it is newer than that and the
 *  air hasn't already reached the forecast level. Older ones are in History. */
function activeAlerts(feed) {
  const latest = lastGood?.readings?.at(-1);
  if (!latest) return [];
  const simulatedNow = latest.source !== "live";
  const since = Date.now() - ACTIVE_HOURS * 3600 * 1000;
  const candidates = feed.filter((a) => a.location === latest.location
    && Date.parse(a.created_at) >= since
    && (a.severity === "warning" || a.severity === "critical" || a.spike === true)
    && a.message.startsWith(SIM_PREFIX) === simulatedNow);  // the feed is newest first

  const levelNow = rankOf(levelOf(lastGood.analysis));
  const current = candidates.find((a) => a.kind !== "forecast");
  const forecast = candidates.find((a) => a.kind === "forecast");
  const shown = [];
  if (current && (levelNow >= rankOf("poor") || current.spike === true)) shown.push(current);
  if (forecast && (!current || forecast.created_at > current.created_at) && levelNow < rankOf(forecast.level)) {
    shown.push(forecast);
  }
  return shown.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
}

let feedContext = null;  // city and live/simulated the panel was built for

function renderFeed(allAlerts) {
  const latest = lastGood?.readings?.at(-1);
  const context = latest ? `${latest.location}|${latest.source}` : null;
  if (context !== feedContext) {  // another city or data mode: rebuild, without "new alert" animation
    $("feed").replaceChildren();
    feedItems.clear();
    feedLoaded = false;
    feedContext = context;
  }
  const feed = activeAlerts(allAlerts);
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
  $("feed-empty").textContent = latest
    ? t("No active alerts for {city}. Warnings appear here when the air reaches Poor, is forecast to, or spikes suddenly.",
        { city: cityName(latest.location) })
    : t("Alerts appear once the server responds.");
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
  const at = new Date().toLocaleTimeString([], { ...PKT, hour: "2-digit", minute: "2-digit", second: "2-digit" });
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
  renderForecast(s);
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
  $("forecast-empty").textContent = t("The forecast appears once the server responds.");
  $("advice-headline").textContent = t("Advice appears once the server responds.");
  for (const who of AUDIENCES) fillList(`aud-${who}`, [], t("Waiting for the server…"));
  if (!feedLoaded) $("feed-empty").textContent = t("Alerts appear once the server responds.");
}

// ---------- all cities: map to scale + ranked list (clicking either switches the dashboard) ----------

// Extent of the 15 cities with a margin (degrees). No borders are drawn: positions are to scale, nothing more.
const MAP = { lonMin: 66.2, lonMax: 75.4, latMin: 24.2, latMax: 34.9 };
const CITIES_MS = 60000;  // live readings are cached for 10 min, so once a minute is plenty
const DOT = 34;           // dot diameter in px; dots closer than this are nudged apart
let lastCities = null;

function renderCities(data) {
  lastCities = data;
  $("cities-empty").hidden = true;
  const map = $("city-map");
  const width = map.clientWidth, height = map.clientHeight;
  if (!width) return;

  // Project to pixels, then nudge overlapping dots apart (Islamabad and Rawalpindi are 11 km apart)
  const pos = data.cities.map((c) => ({
    ...c,
    x: ((c.lon - MAP.lonMin) / (MAP.lonMax - MAP.lonMin)) * width,
    y: ((MAP.latMax - c.lat) / (MAP.latMax - MAP.latMin)) * height,
  }));
  for (let round = 0; round < 40; round++) {
    for (const a of pos) {
      for (const b of pos) {
        if (a === b) continue;
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1;
        if (d < DOT + 2) {
          const push = (DOT + 2 - d) / 2;
          a.x -= (dx / d) * push; a.y -= (dy / d) * push;
          b.x += (dx / d) * push; b.y += (dy / d) * push;
        }
      }
    }
  }

  // A faint graticule every 2 degrees, labelled at the edge
  const grid = svg("svg", { class: "city-map__grid", width, height, "aria-hidden": "true" });
  for (let lat = 26; lat <= 34; lat += 2) {
    const y = ((MAP.latMax - lat) / (MAP.latMax - MAP.latMin)) * height;
    grid.append(svg("line", { x1: 0, x2: width, y1: y, y2: y }), svg("text", { x: 4, y: y - 4 }, `${lat}°N`));
  }
  for (let lon = 68; lon <= 74; lon += 2) {
    const x = ((lon - MAP.lonMin) / (MAP.lonMax - MAP.lonMin)) * width;
    grid.append(svg("line", { x1: x, x2: x, y1: 0, y2: height }), svg("text", { x: x + 4, y: height - 6 }, `${lon}°E`));
  }

  const dots = pos.map((c) => {
    const dot = document.createElement("button");
    dot.type = "button";
    dot.className = "city-dot";
    dot.dataset.level = c.level;
    dot.style.left = `${c.x}px`;
    dot.style.top = `${c.y}px`;
    dot.textContent = c.aqi ?? "–";
    dot.title = `${cityName(c.city)}: ${levelLabel(c.level)}`;
    dot.setAttribute("aria-label", `${cityName(c.city)}, ${levelLabel(c.level)}, ${t("AQI")} ${c.aqi}`);
    dot.setAttribute("aria-pressed", String(c.city === data.current));
    dot.addEventListener("click", () => chooseCity(c.city));
    // The name only where it has room (crowded Punjab dots rely on the list and the tooltip)
    const crowded = pos.some((o) => o !== c && Math.abs(o.x - c.x) < 90 && Math.abs(o.y - c.y) < DOT);
    if (!crowded || c.city === data.current) {
      const name = document.createElement("span");
      // crowded: beside the dot, not below it (and on the left near the right edge)
      name.className = crowded ? `city-dot__name city-dot__name--${c.x > width * 0.7 ? "left" : "side"}` : "city-dot__name";
      name.textContent = cityName(c.city);
      dot.append(name);
    }
    return dot;
  });
  map.replaceChildren(grid, ...dots);
  $("days-note").hidden = !data.cities.some((c) => c.past_days?.length);

  // Ranked list: worst air first
  $("city-list").replaceChildren(...[...data.cities].sort((a, b) => (b.aqi ?? -1) - (a.aqi ?? -1)).map((c) => {
    const li = document.createElement("li");
    const row = document.createElement("button");
    row.type = "button";
    row.className = "city-row";
    row.setAttribute("aria-pressed", String(c.city === data.current));
    const name = document.createElement("span");
    name.className = "city-row__name";
    name.textContent = cityName(c.city);
    const tag = document.createElement("span");
    tag.className = "level-tag";
    tag.dataset.level = c.level;
    tag.textContent = levelLabel(c.level);
    const aqi = document.createElement("span");
    aqi.className = "city-row__aqi";
    aqi.textContent = c.aqi ?? "–";
    row.append(name, pastDays(c.past_days), tag, aqi);
    row.addEventListener("click", () => chooseCity(c.city));
    li.append(row);
    return li;
  }));
}

/** The last 7 days as small squares coloured by level, with a count of Poor-or-worse days for screen readers */
function pastDays(days) {
  const strip = document.createElement("span");
  strip.className = "days";
  if (!days?.length) return strip;
  const bad = days.filter((d) => ["poor", "very_poor", "severe"].includes(d.level)).length;
  strip.setAttribute("role", "img");
  strip.setAttribute("aria-label", t("{bad} of the last {n} days Poor or worse", { bad, n: days.length }));
  strip.append(...days.map((d) => {
    const day = document.createElement("i");
    day.dataset.level = d.level in LEVELS ? d.level : "unknown";
    day.title = `${new Date(`${d.date}T12:00:00+05:00`).toLocaleDateString(LANG === "ur" ? "ur" : [], { ...PKT, weekday: "short", day: "numeric", month: "short" })}: `
      + `${levelLabel(d.level)} (${t("AQI")} ${d.aqi})`;
    return day;
  }));
  return strip;
}

function chooseCity(city) {
  if (city === lastCities?.current) return;
  $("city").value = city;
  changeControl(`/api/city/${encodeURIComponent(city)}`, t("Switching to {city}…", { city: cityName(city) }),
                t("Now showing {city}.", { city: cityName(city) }));
}

let citiesTimer = null;
async function pollCities() {
  clearTimeout(citiesTimer);
  try {
    renderCities(await getJSON("/api/cities"));
  } catch (error) {
    console.error(error);
    if (!lastCities) $("cities-empty").textContent = t("The map appears once the server responds.");
  } finally {
    citiesTimer = setTimeout(pollCities, CITIES_MS);
  }
}

new ResizeObserver(() => { if (lastCities) renderCities(lastCities); }).observe($("city-map"));

// ---------- demo controls (city, scenario, emergency button) ----------

let controlsLoaded = false;
let linkedCity = new URLSearchParams(location.search).get("city");  // ?city=Kasur opens that city, once

/** Keeps ?city= in the address in step with the city on screen, so the link can be shared */
function syncCityInUrl(city) {
  const params = new URLSearchParams(location.search);
  params.set("city", city);
  history.replaceState(null, "", `?${params}`);
}

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
  const wanted = linkedCity && city.options.find((c) => c.toLowerCase() === linkedCity.trim().toLowerCase());
  linkedCity = null;
  if (wanted && wanted !== city.current) {
    chooseCity(wanted);  // reloads the controls (and the address) once the switch is done
  } else {
    syncCityInUrl(city.current);
  }
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
    pollCities();  // the map follows the city and scenario
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
  $("ask-basis").hidden = true;
  $("ask-input").disabled = $("ask-button").disabled = true;
  try {
    const reply = await getJSON("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    answer.dataset.state = reply.source === "ai" ? "" : "note";  // off / busy / unsure: calm, not an error
    answer.textContent = reply.answer;
    const b = reply.based_on;
    $("ask-basis").hidden = !b;
    if (b) {
      $("ask-basis").textContent = (reply.model ? `${t("Answered by AI ({model} on Groq)", { model: shortModel(reply.model) })} · ` : "") +
        `${t("Based on")}: ` + [cityName(b.city), levelLabel(b.level), `${t("AQI")} ${b.aqi}`,
        b.time && t("reading for {time}", { time: localTime(b.time) }), t(b.data_source === "live" ? "live" : "simulated")]
        .filter(Boolean).join(" · ");
    }
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
  if (lastCities) renderCities(lastCities);
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
pollCities();
