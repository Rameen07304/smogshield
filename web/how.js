// "How it works" page (Screen 2): the static explanation is plain HTML; this script only fills the
// live example strip from /api/status, on the same poll interval as the dashboard.
// Needs common.js first. textContent only; the last good values stay on screen if a poll fails.
// Every visible string goes through t() so the page works in Urdu.
"use strict";

const SIM_PREFIX = "[SIMULATION] ";
const SEVERITY_LABELS = { info: "Info", warning: "Warning", critical: "Critical" };  // shapes come from CSS
let liveLoaded = false;
let last = null;  // { s, feed } from the last good poll, re-rendered when the language changes

function setText(id, text) {
  $(id).textContent = text;
}

function renderLive(s, feed) {
  const readings = s.readings || [];
  const latest = readings.at(-1);
  const a = s.analysis || {};
  const level = levelOf(a);
  const known = level !== "unknown";
  const simulated = latest ? latest.source !== "live" : false;
  const ur = LANG === "ur";

  // Header: live or simulated, and when
  const badge = $("mode-badge");
  badge.dataset.mode = latest ? (simulated ? "simulated" : "live") : "loading";
  badge.textContent = t(latest ? (simulated ? "Simulated data" : "Live data") : "No data");
  setText("live-updated", t("Updated {time}", {
    time: new Date().toLocaleTimeString([], { ...PKT, hour: "2-digit", minute: "2-digit", second: "2-digit" }),
  }));

  // Monitor: the reading it fetched
  if (latest) {
    setText("live-monitor", `${cityName(latest.location)}: ` + isolate(`PM2.5 ${latest.pm25} µg/m³` +
      (latest.pm10 != null ? ` · PM10 ${latest.pm10} µg/m³` : "")));
    setText("live-monitor-sub", t("{n} hourly readings, {source}.", {
      n: readings.length, source: t(simulated ? "simulated (demo)" : "live from Open-Meteo"),
    }));
  } else {
    setText("live-monitor", t("No readings"));
    setText("live-monitor-sub", t("The monitor returned nothing usable this time."));
  }

  // Forecast: the next 6 hours, and the best time to go out
  const f = s.forecast || {};
  const six = f.next_6h;
  if (six) {
    setText("live-forecast", t("Peaks {level} (AQI {aqi}) in the next 6 h", { level: levelLabel(six.peak_level), aqi: six.peak_aqi }));
    const best = f.best_time;
    setText("live-forecast-sub",
      (best ? `${t("Best time outside: {from} to {to}.", { from: localTime(best.start), to: localTime(best.end) })} ` : "") +
      t(f.source === "live" ? "Model forecast from Open-Meteo." : "Simulated forecast (demo)."));
  } else {
    setText("live-forecast", t("No forecast"));
    setText("live-forecast-sub", t("The forecast agent had no data this time."));
  }

  // Analysis: AQI on its color, with the category written out
  const pill = $("live-aqi");
  pill.dataset.level = level;
  pill.textContent = known ? a.aqi : "—";
  const rate = Math.abs(a.trend_per_hour ?? 0);
  setText("live-analysis-sub", known
    ? `${levelLabel(level)} · ${trendWord(a.trend)}` +
      (a.trend !== "stable" ? ` ${t("{rate} µg/m³ per hour", { rate })}` : "") + (a.is_spike ? ` · ${t("sudden spike")}` : "")
    : t("Data unavailable: no valid readings"));

  // Advisory: the headline, plus the time note if there is one (in the site language)
  const adv = (ur && s.advisory?.urdu) || s.advisory || {};
  setText("live-advice", adv.headline || t("No advice this time."));
  setText("live-advice-sub", adv.time_note || t("Plus specific advice for 5 groups, in English and Urdu."));

  // Alert: the newest alert in the feed, if any
  const box = $("live-alert");
  const newest = feed[0];
  if (!newest) {
    box.textContent = t("No alerts yet");
    setText("live-alert-sub", t("Alerts start when the air crosses a threshold or spikes."));
  } else {
    const simulatedAlert = newest.message.startsWith(SIM_PREFIX);
    const text = (ur && newest.message_ur) || newest.message;
    const item = document.createElement("div");
    item.className = "alert-item";
    item.dataset.severity = newest.severity in SEVERITY_LABELS ? newest.severity : "warning";
    if (simulatedAlert) item.dataset.simulated = "";
    const top = document.createElement("div");
    top.className = "alert-item__top";
    const badgeEl = document.createElement("span");
    badgeEl.className = "sev-badge";
    badgeEl.textContent = t(SEVERITY_LABELS[newest.severity] ?? newest.severity);
    top.append(badgeEl);
    if (simulatedAlert) {
      const tag = document.createElement("span");
      tag.className = "sim-tag";
      tag.textContent = t("Simulated");
      top.append(tag);
    }
    const message = document.createElement("p");
    message.className = "alert-item__message";
    message.dir = "auto";
    message.textContent = text.startsWith(SIM_PREFIX) ? text.slice(SIM_PREFIX.length) : text;
    item.append(top, message);
    box.replaceChildren(item);
    const raisedNow = (s.alerts || []).length > 0;
    setText("live-alert-sub", t(raisedNow ? "Raised on this run, at {time}." : "Raised at {time}. No new alert on this run.",
                                { time: localTime(newest.created_at) }));
  }

  $("live-offline").hidden = true;
  liveLoaded = true;
}

function liveOffline(error) {
  console.error(error);
  const note = $("live-offline");
  note.hidden = false;
  $("mode-badge").dataset.mode = "offline";
  $("mode-badge").textContent = t("Offline");
  if (liveLoaded) {
    note.textContent = t("Can't reach the SmogShield server, so the live example is paused on the last values. Retrying…");
    return;
  }
  note.textContent = t("Can't reach the SmogShield server yet, so there is no live example. Everything above still explains how it works. Retrying…");
  for (const id of ["live-monitor", "live-forecast", "live-advice", "live-alert"]) setText(id, t("Waiting for the server…"));
  setText("live-analysis-sub", t("Waiting for the server…"));
}

let liveTimer = null;
async function pollLive() {
  clearTimeout(liveTimer);
  try {
    const s = await getJSON("/api/status");      // runs the pipeline, which may add an alert…
    const feed = await getJSON("/api/alerts?limit=1");  // …so read the newest alert afterwards
    last = { s, feed };
    renderLive(s, feed);
  } catch (error) {
    liveOffline(error);
  } finally {
    liveTimer = setTimeout(pollLive, POLL_MS);
  }
}

document.addEventListener("languagechange", () => { if (last) renderLive(last.s, last.feed); });
pollLive();
