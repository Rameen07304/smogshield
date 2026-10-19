// Alert history page (Screen 3): a table of every stored alert, newest first.
// Reads /api/alerts only (it never runs the pipeline). Needs common.js first.
// textContent only; the last good table stays on screen if a refresh fails.
// Every visible string goes through t() so the page works in Urdu.
"use strict";

const HISTORY_LIMIT = 1000;  // everything the alert store keeps: 7 days, at most 1000 (agents/alert.py)
const PAGE_SIZE = 25;        // rows shown at first; "Show more" adds this many
const DAY_MS = 24 * 3600 * 1000;
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
  tr.dataset.severity = a.severity;  // critical rows are tinted
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

// ---------- filters (kept in the URL, e.g. ?urgency=critical&source=simulated&city=Lahore) ----------

// The first value of each list is the default (left out of the URL)
const FILTER_VALUES = { period: ["day", "week"], urgency: ["all", "info", "warning", "critical"],
  source: ["all", "real", "simulated"], kind: ["all", "current", "forecast"] };
const filters = { period: "day", urgency: "all", source: "all", kind: "all", city: "all" };
const defaultOf = (name) => FILTER_VALUES[name]?.[0] ?? "all";
const MATCHERS = {
  period: (a, v) => Date.now() - Date.parse(a.created_at) <= (v === "day" ? DAY_MS : 7 * DAY_MS),
  urgency: (a, v) => v === "all" || a.severity === v,
  source: (a, v) => v === "all" || (v === "simulated") === isSimulated(a),
  kind: (a, v) => v === "all" || (a.kind || "current") === v,  // old alerts have no kind: they were current
  city: (a, v) => v === "all" || a.location === v,
};
/** Every filter matches, except the one named (so each option's count assumes the other filters) */
const matches = (a, except) => Object.keys(filters).every((name) => name === except || MATCHERS[name](a, filters[name]));

function readFiltersFromUrl() {
  const params = new URLSearchParams(location.search);
  for (const [name, allowed] of Object.entries(FILTER_VALUES)) {
    const value = params.get(name);
    filters[name] = allowed.includes(value) ? value : allowed[0];
    const radio = document.querySelector(`input[name="${name}"][value="${filters[name]}"]`);
    if (radio) radio.checked = true;
  }
  filters.city = params.get("city") || "all";  // checked against the alerts' cities once they load
}

function writeFiltersToUrl() {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(filters)) if (value !== defaultOf(name)) params.set(name, value);
  const lang = new URLSearchParams(location.search).get("lang");
  if (lang) params.set("lang", lang);
  const query = params.toString();
  history.replaceState(null, "", query ? `?${query}` : location.pathname);
}

/** How many alerts each option would show, given the other filters (so the numbers always add up) */
function updateCounts() {
  for (const [name, values] of Object.entries(FILTER_VALUES)) {
    for (const value of values) {
      const n = alerts.filter((a) => MATCHERS[name](a, value) && matches(a, name)).length;
      document.querySelector(`[data-count="${name}-${value}"]`).textContent = n;
    }
  }
}

/** City options: the cities that have alerts, A to Z, each with its count */
function renderCityOptions() {
  const cities = [...new Set(alerts.map((a) => a.location))].sort();
  if (!cities.includes(filters.city)) filters.city = "all";
  const option = (value, label) => {
    const o = document.createElement("option");
    o.value = value;
    o.textContent = `${label} (${alerts.filter((a) => MATCHERS.city(a, value) && matches(a, "city")).length})`;
    return o;
  };
  const select = $("city-filter");
  select.replaceChildren(option("all", t("All cities")), ...cities.map((c) => option(c, cityName(c))));
  select.value = filters.city;
}

$("filters").addEventListener("change", (event) => {
  if (!(event.target.name in filters)) return;
  filters[event.target.name] = event.target.value;
  visible = PAGE_SIZE;
  writeFiltersToUrl();
  renderHistory();
});

$("clear-filters").addEventListener("click", () => {
  for (const name of Object.keys(filters)) filters[name] = defaultOf(name);
  filters.period = "week";  // "show all" means everything kept, not just today
  for (const [name, value] of Object.entries(filters)) {
    const radio = document.querySelector(`#filters input[name="${name}"][value="${value}"]`);
    if (radio) radio.checked = true;
  }
  visible = PAGE_SIZE;
  writeFiltersToUrl();
  renderHistory();
});

let visible = PAGE_SIZE;
$("history-more").addEventListener("click", () => { visible += PAGE_SIZE; renderHistory(); });

/** "Today", "Yesterday" or "Fri 17 Oct", for the Pakistan calendar day of an alert */
function dayLabel(iso) {
  const key = (time) => new Date(time).toLocaleDateString("en-CA", PKT);  // YYYY-MM-DD in Pakistan
  const day = key(iso);
  if (day === key(Date.now())) return t("Today");
  if (day === key(Date.now() - DAY_MS)) return t("Yesterday");
  return isolate(new Date(iso).toLocaleDateString([], { ...PKT, weekday: "short", day: "numeric", month: "short" }));
}

/** The rows, with a heading row wherever a new day starts */
function rowsByDay(list) {
  const rows = [];
  let current = null;
  for (const a of list) {
    const label = dayLabel(a.created_at);
    if (label !== current) {
      current = label;
      const tr = document.createElement("tr");
      tr.className = "history__day";
      const th = document.createElement("th");
      th.scope = "colgroup";
      th.colSpan = 7;
      th.textContent = label;
      tr.append(th);
      rows.push(tr);
    }
    rows.push(buildRow(a));
  }
  return rows;
}

function renderHistory() {
  renderCityOptions();
  const shown = alerts.filter((a) => matches(a));
  $("history-rows").replaceChildren(...rowsByDay(shown.slice(0, visible)));
  const more = shown.length - visible;
  $("history-more").hidden = more <= 0;
  $("history-more").textContent = t("Show {n} more", { n: Math.min(more, PAGE_SIZE) });
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
