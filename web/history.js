// Alert history page (Screen 3): a table of every stored alert, newest first.
// Reads /api/alerts only (it never runs the pipeline). Needs common.js first.
// textContent only; the last good table stays on screen if a refresh fails.
// Every visible string goes through t() so the page works in Urdu.
"use strict";

const HISTORY_LIMIT = 100;  // the alert store keeps the newest 100 (FEED_SIZE in agents/alert.py)
const SIM_PREFIX = "[SIMULATION] ";
const URGENCY = {  // the shape beside each word is drawn in CSS, so colour is never the only cue
  info: { label: "Info" },
  warning: { label: "Warning" },
  critical: { label: "Critical" },
};
let alerts = [];
let historyLoaded = false;

const isSimulated = (a) => a.message.startsWith(SIM_PREFIX);

/** "sent" | "queued" | "failed: telegram: <why>" -> { kind, label, detail } */
function delivery(a) {
  if (a.status === "sent") return { kind: "sent", label: t("Sent"), detail: "" };
  if (a.status === "queued") return { kind: "queued", label: t("Queued"), detail: t("Sending to Telegram") };
  const detail = a.status.replace(/^failed:\s*/, "");
  return { kind: "failed", label: t("Failed"), detail: detail ? t("{detail} (kept in the dashboard feed)", { detail }) : "" };
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
  const stamp = document.createElement("time");
  stamp.dateTime = a.created_at;
  stamp.append(span(isolate(when.toLocaleDateString([], { ...PKT, day: "numeric", month: "short" })), "history__date"),
           span(isolate(when.toLocaleTimeString([], { ...PKT, hour: "2-digit", minute: "2-digit", second: "2-digit" })), "history__clock"));
  time.append(stamp);

  // Level: the category name on its AQI color
  const level = cell();
  const pill = span(levelLabel(a.level), "level-tag");
  pill.dataset.level = a.level in LEVELS ? a.level : "unknown";
  level.append(pill);

  // Urgency: a badge with icon + word (colour is never the only cue)
  const urgency = cell();
  const sev = URGENCY[a.severity] ?? { label: a.severity.toUpperCase() };
  const badge = span(t(sev.label), "sev-badge");
  const badgeWrap = span("", "alert-item");  // reuses the severity colors from the alert feed
  badgeWrap.dataset.severity = a.severity in URGENCY ? a.severity : "warning";
  badgeWrap.classList.add("history__sev");
  badgeWrap.append(badge);
  urgency.append(badgeWrap);

  // Message, with the [SIMULATION] prefix turned into a tag
  const message = cell(null, "history__message");
  if (simulated) message.append(span(t("Simulated"), "sim-tag"), " ");
  const text = (LANG === "ur" && a.message_ur) || a.message;
  const body = span(text.startsWith(SIM_PREFIX) ? text.slice(SIM_PREFIX.length) : text, "");
  body.dir = "auto";  // an English message keeps left-to-right order inside the Urdu page
  message.append(body);

  // Channel and delivery
  const channel = cell(t(a.channel === "telegram" ? "Telegram" : "Dashboard feed"));
  const d = delivery(a);
  const status = cell();
  const chip = span(d.label, "delivery");
  chip.dataset.kind = d.kind;
  status.append(chip);
  if (d.detail) status.append(span(d.detail, "delivery__detail"));

  // Labels for the stacked phone layout
  const labels = ["Time", "Location", "Level", "Urgency", "Message", "Channel", "Delivery"].map((label) => t(label));
  const cells = [time, cell(cityName(a.location)), level, urgency, message, channel, status];
  cells.forEach((td, i) => { td.dataset.label = labels[i]; });
  tr.append(...cells);
  return tr;
}

// ---------- filters (kept in the URL, e.g. ?urgency=critical&source=simulated) ----------

const FILTER_VALUES = { urgency: ["all", "info", "warning", "critical"], source: ["all", "real", "simulated"] };
const filters = { urgency: "all", source: "all" };

const matchesUrgency = (a, urgency) => urgency === "all" || a.severity === urgency;
const matchesSource = (a, source) => source === "all" || (source === "simulated") === isSimulated(a);
const matches = (a) => matchesUrgency(a, filters.urgency) && matchesSource(a, filters.source);

function readFiltersFromUrl() {
  const params = new URLSearchParams(location.search);
  for (const [name, allowed] of Object.entries(FILTER_VALUES)) {
    const value = params.get(name);
    filters[name] = allowed.includes(value) ? value : "all";
    const radio = document.querySelector(`input[name="${name}"][value="${filters[name]}"]`);
    if (radio) radio.checked = true;
  }
}

function writeFiltersToUrl() {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(filters)) if (value !== "all") params.set(name, value);
  const query = params.toString();
  history.replaceState(null, "", query ? `?${query}` : location.pathname);
}

/** How many alerts each option would show, given the other filter (so the numbers always add up) */
function updateCounts() {
  for (const urgency of FILTER_VALUES.urgency) {
    const n = alerts.filter((a) => matchesUrgency(a, urgency) && matchesSource(a, filters.source)).length;
    document.querySelector(`[data-count="urgency-${urgency}"]`).textContent = n;
  }
  for (const source of FILTER_VALUES.source) {
    const n = alerts.filter((a) => matchesSource(a, source) && matchesUrgency(a, filters.urgency)).length;
    document.querySelector(`[data-count="source-${source}"]`).textContent = n;
  }
}

$("filters").addEventListener("change", (event) => {
  if (!(event.target.name in filters)) return;
  filters[event.target.name] = event.target.value;
  writeFiltersToUrl();
  renderHistory();
});

$("clear-filters").addEventListener("click", () => {
  filters.urgency = "all";
  filters.source = "all";
  for (const radio of document.querySelectorAll('#filters input[value="all"]')) radio.checked = true;
  writeFiltersToUrl();
  renderHistory();
});

function renderHistory() {
  const shown = alerts.filter(matches);
  $("history-rows").replaceChildren(...shown.map(buildRow));
  const none = alerts.length === 0;
  $("filters").hidden = none;
  $("history-table").hidden = shown.length === 0;
  $("history-empty").hidden = !none;
  $("history-empty").textContent = t("No alerts yet. Trigger a scenario on the dashboard.");
  $("history-nomatch").hidden = none || shown.length > 0;
  $("history-count").hidden = none;
  $("history-count").textContent = shown.length === alerts.length
    ? (alerts.length === 1 ? t("1 alert") : t("{n} alerts", { n: alerts.length }))
    : t("Showing {shown} of {all}", { shown: shown.length, all: alerts.length });
  updateCounts();
}

function historyOffline(error) {
  console.error(error);
  const note = $("history-offline");
  note.hidden = false;
  if (historyLoaded) {
    note.textContent = t("Can't reach the SmogShield server. Showing the alerts loaded earlier; retrying…");
  } else {
    note.textContent = t("Can't reach the SmogShield server yet. Retrying…");
    $("history-empty").textContent = t("Alerts appear once the server responds.");
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

document.addEventListener("languagechange", () => { if (historyLoaded) renderHistory(); });
readFiltersFromUrl();
pollHistory();
