// Alert history page (Screen 3): a table of every stored alert, newest first.
// Reads /api/alerts only (it never runs the pipeline). Needs common.js first.
// textContent only; the last good table stays on screen if a refresh fails.
"use strict";

const HISTORY_LIMIT = 100;  // the alert store keeps the newest 100 (FEED_SIZE in agents/alert.py)
const SIM_PREFIX = "[SIMULATION] ";
const URGENCY = {
  info: { label: "INFO", icon: "ℹ" },
  warning: { label: "WARNING", icon: "▲" },
  critical: { label: "CRITICAL", icon: "⬣" },
};
let alerts = [];
let historyLoaded = false;

const isSimulated = (a) => a.message.startsWith(SIM_PREFIX);

/** "sent" | "queued" | "failed: telegram: <why>" -> { kind, label, detail } */
function delivery(a) {
  if (a.status === "sent") return { kind: "sent", label: "✓ Sent", detail: "" };
  if (a.status === "queued") return { kind: "queued", label: "… Queued", detail: "Sending to Telegram" };
  const detail = a.status.replace(/^failed:\s*/, "");
  return { kind: "failed", label: "✕ Failed", detail: detail ? `${detail} (kept in the dashboard feed)` : "" };
}

function cell(text, className) {
  const td = document.createElement("td");
  if (text != null) td.textContent = text;
  if (className) td.className = className;
  return td;
}

function span(text, className) {
  const s = document.createElement("span");
  s.textContent = text;
  s.className = className;
  return s;
}

function buildRow(a) {
  const tr = document.createElement("tr");
  const simulated = isSimulated(a);
  if (simulated) tr.dataset.simulated = "";
  const when = new Date(a.created_at);

  // Time: date on one line, time on the next
  const time = cell(null, "history__time");
  const t = document.createElement("time");
  t.dateTime = a.created_at;
  t.append(span(when.toLocaleDateString([], { day: "numeric", month: "short" }), "history__date"),
           span(when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }), "history__clock"));
  time.append(t);

  // Level: the category name on its AQI color
  const level = cell();
  const pill = span(LEVELS[a.level]?.label ?? a.level, "level-tag");
  pill.dataset.level = a.level in LEVELS ? a.level : "unknown";
  level.append(pill);

  // Urgency: a badge with icon + word (colour is never the only cue)
  const urgency = cell();
  const sev = URGENCY[a.severity] ?? { label: a.severity.toUpperCase(), icon: "" };
  const badge = span(`${sev.icon} ${sev.label}`, "sev-badge");
  const badgeWrap = span("", "alert-item");  // reuses the severity colors from the alert feed
  badgeWrap.dataset.severity = a.severity in URGENCY ? a.severity : "warning";
  badgeWrap.classList.add("history__sev");
  badgeWrap.append(badge);
  urgency.append(badgeWrap);

  // Message, with the [SIMULATION] prefix turned into a tag
  const message = cell(null, "history__message");
  if (simulated) message.append(span("SIMULATION", "sim-tag"), " ");
  message.append(simulated ? a.message.slice(SIM_PREFIX.length) : a.message);

  // Channel and delivery
  const channel = cell(a.channel === "telegram" ? "Telegram" : "Dashboard feed");
  const d = delivery(a);
  const status = cell();
  const chip = span(d.label, "delivery");
  chip.dataset.kind = d.kind;
  status.append(chip);
  if (d.detail) status.append(span(d.detail, "delivery__detail"));

  // Labels for the stacked phone layout
  const labels = ["Time", "Location", "Level", "Urgency", "Message", "Channel", "Delivery"];
  const cells = [time, cell(a.location), level, urgency, message, channel, status];
  cells.forEach((td, i) => { td.dataset.label = labels[i]; });
  tr.append(...cells);
  return tr;
}

function renderHistory() {
  const rows = alerts.map(buildRow);
  $("history-rows").replaceChildren(...rows);
  $("history-table").hidden = alerts.length === 0;
  $("history-empty").hidden = alerts.length > 0;
  $("history-empty").textContent = "No alerts yet. Trigger a scenario on the dashboard.";
  $("history-count").hidden = alerts.length === 0;
  $("history-count").textContent = `${alerts.length} ${alerts.length === 1 ? "alert" : "alerts"}`;
}

function historyOffline(error) {
  console.error(error);
  const note = $("history-offline");
  note.hidden = false;
  if (historyLoaded) {
    note.textContent = "Can't reach the SmogShield server. Showing the alerts loaded earlier; retrying…";
  } else {
    note.textContent = "Can't reach the SmogShield server yet. Retrying…";
    $("history-empty").textContent = "Alerts appear once the server responds.";
  }
}

let historyTimer = null;
async function pollHistory() {
  clearTimeout(historyTimer);
  try {
    alerts = await getJSON(`/api/alerts?limit=${HISTORY_LIMIT}`);  // already newest first
    historyLoaded = true;
    $("history-offline").hidden = true;
    renderHistory();
  } catch (error) {
    historyOffline(error);
  } finally {
    historyTimer = setTimeout(pollHistory, POLL_MS);
  }
}

pollHistory();
