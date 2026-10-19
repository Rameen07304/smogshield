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

// Every time on screen is Pakistan time (like the advice text from the server), whatever zone the computer is in
const PKT = { timeZone: "Asia/Karachi" };
const localTime = (iso) => isolate(new Date(iso).toLocaleTimeString([], { ...PKT, hour: "2-digit", minute: "2-digit" }));
const levelOf = (analysis) => (analysis && analysis.level in LEVELS ? analysis.level : "unknown");

// ---------- language: English / Urdu for the whole site ----------
// Static text: data-i18n (translated on every switch), data-i18n-init (only at load: JS replaces it later),
// data-i18n-html="key" (trusted markup from UR_HTML), data-i18n-placeholder. Dynamic text: t(englishText).
// Pages re-render their last data on the "languagechange" event. Urdu is machine-drafted: needs a native review.

const LANG_KEY = "smogshield.lang";
let LANG = "en";
try { if (localStorage.getItem(LANG_KEY) === "ur") LANG = "ur"; } catch { /* storage blocked: English */ }
const langParam = new URLSearchParams(location.search).get("lang");  // ?lang=ur opens in Urdu
if (langParam === "en" || langParam === "ur") LANG = langParam;

let CITY_UR = {};  // filled from /api/city (one list, kept in agents/monitor.py)

const UR = {
  // header, navigation, controls
  "Live dashboard": "لائیو ڈیش بورڈ", "How it works": "یہ کیسے کام کرتا ہے", "History": "ہسٹری",
  "City": "شہر", "Demo scenario": "ڈیمو منظرنامہ", "Trigger smog emergency": "اسموگ ایمرجنسی چلائیں",
  "Connecting…": "رابطہ ہو رہا ہے…", "Live": "لائیو", "Simulated": "نقلی", "Offline": "آف لائن",
  "No data": "ڈیٹا نہیں", "Simulated data": "نقلی ڈیٹا", "Live data": "لائیو ڈیٹا", "Language": "زبان",
  "Spike: smog builds, then clears": "اچانک اضافہ: اسموگ بڑھتی ہے، پھر چھٹ جاتی ہے",
  "Couldn't change that setting. Is the server running?": "یہ ترتیب تبدیل نہیں ہو سکی۔ کیا سرور چل رہا ہے؟",
  "Switching to {city}…": "{city} پر منتقل ہو رہے ہیں…", "Now showing {city}.": "اب {city} دکھایا جا رہا ہے۔",
  "Switching to “{label}”…": "“{label}” پر منتقل ہو رہے ہیں…", "Back to live data.": "لائیو ڈیٹا پر واپس۔",
  "Demo scenario: {label} (simulated).": "ڈیمو منظرنامہ: {label} (نقلی)۔",
  "Triggering a simulated smog emergency…": "نقلی اسموگ ایمرجنسی شروع کی جا رہی ہے…",
  "Smog emergency triggered (simulated data).": "اسموگ ایمرجنسی شروع (نقلی ڈیٹا)۔",
  "Demo controls unavailable until the server responds.": "سرور کے جواب تک ڈیمو کنٹرول دستیاب نہیں۔",
  // levels, trends, severity
  "Good": "اچھا", "Satisfactory": "قابلِ قبول", "Moderate": "درمیانہ", "Poor": "خراب", "Very Poor": "بہت خراب",
  "Very poor": "بہت خراب", "Severe": "شدید", "Satisf.": "قابلِ قبول", "Data unavailable": "ڈیٹا دستیاب نہیں",
  "rising": "بڑھ رہا ہے", "falling": "کم ہو رہا ہے", "steady": "مستحکم",
  "Info": "معلومات", "Warning": "انتباہ", "Critical": "سنگین", "All": "سب", "Real": "اصل",
  // banners
  "Demo scenario: these are not real air quality readings.": "ڈیمو منظرنامہ: یہ ہوا کے معیار کی اصل ریڈنگز نہیں ہیں۔",
  "Live data is unavailable right now, so these are simulated readings, not real air quality.":
    "لائیو ڈیٹا اس وقت دستیاب نہیں، اس لیے یہ نقلی ریڈنگز ہیں، ہوا کا اصل معیار نہیں۔",
  "Can't reach the SmogShield server yet. Retrying every few seconds…":
    "اسموگ شیلڈ سرور سے ابھی رابطہ نہیں ہو سکا۔ ہر چند سیکنڈ بعد دوبارہ کوشش…",
  "Can't reach the SmogShield server. Showing data from {at}; retrying…":
    "اسموگ شیلڈ سرور سے رابطہ نہیں۔ {at} کا ڈیٹا دکھایا جا رہا ہے؛ دوبارہ کوشش…",
  "the last refresh": "آخری ریفریش",
  // hero
  "AQI (hourly estimate)": "اے کیو آئی (گھنٹہ وار اندازہ)", "AQI": "اے کیو آئی", "Loading…": "لوڈ ہو رہا ہے…",
  "Loading live air quality…": "ہوا کا لائیو معیار لوڈ ہو رہا ہے…",
  "Fetching the latest readings.": "تازہ ترین ریڈنگز حاصل کی جا رہی ہیں۔",
  "reading for {time}": "{time} کی ریڈنگ", "No current readings": "کوئی موجودہ ریڈنگ نہیں",
  "No valid readings right now. Take precautions until data is back.":
    "اس وقت کوئی درست ریڈنگ نہیں۔ ڈیٹا واپس آنے تک احتیاط کریں۔",
  "AQI driven by PM10": "اے کیو آئی PM10 کی وجہ سے", "Waiting for valid readings.": "درست ریڈنگز کا انتظار ہے۔",
  "{name} is {x}× the national 24-hour target ({target} µg/m³)":
    "{name} قومی 24 گھنٹے کے ہدف ({target} µg/m³) کا {x} گنا ہے",
  "Hourly value vs a 24-hour target.": "گھنٹہ وار قدر کا موازنہ 24 گھنٹے کے ہدف سے۔",
  "Not connected": "رابطہ نہیں", "Waiting for the server": "سرور کا انتظار",
  "Start it with: uvicorn app:app": "اسے شروع کریں: uvicorn app:app",
  // pipeline
  "How the agents got there": "ایجنٹس اس نتیجے تک کیسے پہنچے", "Monitor": "مانیٹر", "Forecast": "پیش گوئی",
  "Analysis": "تجزیہ", "Advisory": "مشورہ", "Alert": "الرٹ",
  "Collects air readings": "ہوا کی ریڈنگز جمع کرتا ہے", "Looks ahead 24 hours": "اگلے 24 گھنٹے دیکھتا ہے",
  "Scores AQI, trend, spikes": "اے کیو آئی، رجحان اور اچانک اضافہ جانچتا ہے",
  "Writes guidance per group": "ہر گروپ کے لیے رہنمائی لکھتا ہے", "Decides whether to warn": "انتباہ کا فیصلہ کرتا ہے",
  "Waiting…": "انتظار…", "Waiting for the first run…": "پہلے رن کا انتظار…",
  "{n} hourly readings": "{n} گھنٹہ وار ریڈنگز", "live": "لائیو", "simulated": "نقلی",
  "No readings": "کوئی ریڈنگ نہیں", "No valid readings": "کوئی درست ریڈنگ نہیں", "spike!": "اچانک اضافہ!",
  "Advice for 5 groups + Urdu": "5 گروپس کے لیے مشورہ + اردو", "Cautious default advice": "محتاط عمومی مشورہ",
  "{sev} alert raised": "{sev} الرٹ جاری", "No alert without data": "ڈیٹا کے بغیر کوئی الرٹ نہیں",
  "No new alert": "کوئی نیا الرٹ نہیں", "No forecast available": "پیش گوئی دستیاب نہیں",
  "Next 6 h peaks {level} (AQI {aqi})": "اگلے 6 گھنٹوں میں زیادہ سے زیادہ {level} (اے کیو آئی {aqi})",
  "Last run {at} · refreshes every {s} s": "آخری رن {at} · ہر {s} سیکنڈ میں تازہ",
  "Pipeline unreachable: waiting for the server…": "پائپ لائن تک رسائی نہیں: سرور کا انتظار…",
  // chart
  "PM2.5 over the recent window": "حالیہ گھنٹوں میں PM2.5", "Steady": "مستحکم",
  "Rising {rate} µg/m³ per hour": "{rate} µg/m³ فی گھنٹہ بڑھ رہا ہے",
  "Falling {rate} µg/m³ per hour": "{rate} µg/m³ فی گھنٹہ کم ہو رہا ہے", "Sudden spike": "اچانک اضافہ",
  "Loading the recent readings…": "حالیہ ریڈنگز لوڈ ہو رہی ہیں…",
  "No valid readings to chart right now.": "چارٹ کے لیے اس وقت کوئی درست ریڈنگ نہیں۔",
  "PM2.5 went from {first} to {last} µg/m³ over {n} hourly readings: {trend}":
    "{n} گھنٹہ وار ریڈنگز میں PM2.5 {first} سے {last} µg/m³ ہوا: {trend}",
  "with a sudden spike in the latest hour": "تازہ ترین گھنٹے میں اچانک اضافے کے ساتھ",
  "Spike · {v}": "اچانک اضافہ · {v}", "The chart appears once the server responds.": "سرور کے جواب دینے پر چارٹ ظاہر ہوگا۔",
  // all cities
  "Based on": "بنیاد",
  "Type": "قسم", "Now": "ابھی", "All cities": "تمام شہر",
  "Advice written by AI ({model} on Groq), checked against the NCAP categories.":
    "یہ مشورہ AI ‏({model}، Groq) نے لکھا اور NCAP زمروں سے جانچا گیا۔",
  "Advice from SmogShield's NCAP rules.": "یہ مشورہ SmogShield کے NCAP اصولوں سے ہے۔",
  "Answered by AI ({model} on Groq)": "جواب AI ‏({model}، Groq) نے دیا", "Data may be delayed: the latest reading is {h} hours old.":
    "ڈیٹا میں تاخیر ہو سکتی ہے: تازہ ترین ریڈنگ {h} گھنٹے پرانی ہے۔",
  "Air across Pakistan": "پاکستان بھر میں ہوا", "Choose a city to see it in detail.": "تفصیل دیکھنے کے لیے کوئی شہر منتخب کریں۔",
  "Loading all cities…": "تمام شہر لوڈ ہو رہے ہیں…", "The map appears once the server responds.": "سرور کے جواب دینے پر نقشہ ظاہر ہوگا۔",
  // forecast
  "Next 24 hours": "اگلے 24 گھنٹے", "Loading the forecast…": "پیش گوئی لوڈ ہو رہی ہے…",
  "No forecast available right now.": "اس وقت پیش گوئی دستیاب نہیں۔", "Best time": "بہترین وقت",
  "Best time outside: {from}–{to}": "باہر جانے کا بہترین وقت: {from} سے {to} تک",
  "Peaks at {level} (AQI {aqi}) around {time}. A model estimate: most reliable for the next 6 hours.":
    "تقریباً {time} پر زیادہ سے زیادہ {level} (اے کیو آئی {aqi})۔ یہ ماڈل کا اندازہ ہے: اگلے 6 گھنٹوں کے لیے سب سے قابلِ اعتماد۔",
  "Coming days": "آنے والے دن", "Today": "آج", "peak AQI {aqi}": "زیادہ سے زیادہ اے کیو آئی {aqi}",
  "Simulated forecast": "نقلی پیش گوئی", "The forecast appears once the server responds.": "سرور کے جواب دینے پر پیش گوئی ظاہر ہوگی۔",
  // alert feed
  "Alert feed": "الرٹ فیڈ", "Loading alerts…": "الرٹس لوڈ ہو رہے ہیں…", "All alerts in History": "تمام الرٹس ہسٹری میں",
  "Couldn't refresh alerts. Showing the last ones received.": "الرٹس تازہ نہیں ہو سکے۔ آخری موصول شدہ دکھائے جا رہے ہیں۔",
  "No alerts yet. They appear here when air quality crosses a threshold or spikes.":
    "ابھی کوئی الرٹ نہیں۔ جب ہوا کا معیار حد سے بڑھے یا اچانک بگڑے تو یہاں ظاہر ہوں گے۔",
  "{n} alerts": "{n} الرٹس", "1 alert": "1 الرٹ", "Sending to Telegram…": "ٹیلیگرام پر بھیجا جا رہا ہے…",
  "Sent via Telegram": "ٹیلیگرام سے بھیجا گیا", "Dashboard feed": "ڈیش بورڈ فیڈ",
  "Telegram failed, kept in the feed": "ٹیلیگرام ناکام، فیڈ میں محفوظ",
  "Alerts appear once the server responds.": "سرور کے جواب دینے پر الرٹس ظاہر ہوں گے۔",
  "{sev} alert: {msg}": "{sev} الرٹ: {msg}",
  // advice and Ask
  "What to do": "کیا کریں", "Loading advice…": "مشورہ لوڈ ہو رہا ہے…",
  "Advice is unavailable right now. Take care outdoors.": "مشورہ اس وقت دستیاب نہیں۔ باہر احتیاط کریں۔",
  "General public": "عام لوگ", "Children & schools": "بچے اور اسکول", "Elderly": "بزرگ",
  "Heart & lung conditions": "دل اور پھیپھڑوں کے مریض", "Outdoor workers": "باہر کام کرنے والے",
  "No specific advice for this group right now.": "اس گروپ کے لیے اس وقت کوئی خاص مشورہ نہیں۔",
  "General guidance, not medical advice.": "عمومی رہنمائی، طبی مشورہ نہیں۔",
  "Advice appears once the server responds.": "سرور کے جواب دینے پر مشورہ ظاہر ہوگا۔",
  "Waiting for the server…": "سرور کا انتظار…", "Ask about today's air": "آج کی ہوا کے بارے میں پوچھیں",
  "Ask": "پوچھیں", "Can my kids play outside this evening?": "کیا میرے بچے آج شام باہر کھیل سکتے ہیں؟",
  "Thinking…": "سوچ رہا ہے…",
  "Couldn't reach SmogShield. The advice above still applies.": "اسموگ شیلڈ سے رابطہ نہیں ہو سکا۔ اوپر دیا گیا مشورہ اب بھی لاگو ہے۔",
  // how it works
  "How SmogShield works": "اسموگ شیلڈ کیسے کام کرتا ہے", "The pipeline": "پائپ لائن", "Receives": "وصول کرتا ہے",
  "Produces": "تیار کرتا ہے", "What each agent produced just now": "ہر ایجنٹ نے ابھی کیا تیار کیا",
  "Monitor read": "مانیٹر نے پڑھا", "Forecast expects": "پیش گوئی کے مطابق", "Analysis scored": "تجزیے کا نتیجہ",
  "Advisory said": "مشورہ", "Alert's latest": "تازہ ترین الرٹ", "Data and honesty": "ڈیٹا اور دیانت داری",
  "Built to be reliable": "قابلِ اعتماد ڈیزائن",
  "Fetches and cleans air quality readings.": "ہوا کے معیار کی ریڈنگز حاصل کر کے صاف کرتا ہے۔",
  "A city, plus live data from Open-Meteo (or a demo scenario).": "ایک شہر، اور Open-Meteo سے لائیو ڈیٹا (یا ڈیمو منظرنامہ)۔",
  "The last 6 hourly readings: PM2.5, PM10, the time, and whether they are live or simulated.":
    "آخری 6 گھنٹہ وار ریڈنگز: PM2.5، PM10، وقت، اور یہ کہ وہ لائیو ہیں یا نقلی۔",
  "Looks ahead at the next 24 hours.": "اگلے 24 گھنٹوں کی پیش گوئی کرتا ہے۔",
  "The city and its current reading.": "شہر اور اس کی موجودہ ریڈنگ۔",
  "An hourly PM2.5 forecast, 6 and 24 hour summaries, the best time to go outside, and a daily outlook.":
    "گھنٹہ وار PM2.5 پیش گوئی، 6 اور 24 گھنٹے کا خلاصہ، باہر جانے کا بہترین وقت، اور روزانہ کا جائزہ۔",
  "Computes the AQI, the trend and sudden spikes.": "اے کیو آئی، رجحان اور اچانک اضافے کا حساب لگاتا ہے۔",
  "The recent readings.": "حالیہ ریڈنگز۔",
  "An AQI number, a category (Good to Severe), the trend per hour, a spike flag and a one-line reason.":
    "اے کیو آئی کا عدد، زمرہ (اچھا سے شدید تک)، فی گھنٹہ رجحان، اچانک اضافے کا نشان اور ایک سطری وجہ۔",
  "The assessment and the forecast.": "جائزہ اور پیش گوئی۔",
  "A headline and advice for the public, children and schools, the elderly, people with heart or lung conditions, and outdoor workers.":
    "سرخی، اور عام لوگوں، بچوں اور اسکولوں، بزرگوں، دل یا پھیپھڑوں کے مریضوں اور باہر کام کرنے والوں کے لیے مشورہ۔",
  "Decides when and how to notify people, without spamming them.": "فیصلہ کرتا ہے کہ لوگوں کو کب اور کیسے خبردار کیا جائے، بغیر بار بار تنگ کیے۔",
  "The assessment, the forecast, the advice and the location.": "جائزہ، پیش گوئی، مشورہ اور مقام۔",
  "An info, warning or critical alert in the dashboard feed (and Telegram, if set up), or nothing when nothing changed.":
    "ڈیش بورڈ فیڈ میں (اور اگر ترتیب ہو تو ٹیلیگرام پر) معلوماتی، انتباہی یا سنگین الرٹ، یا کچھ نہیں جب کچھ نہ بدلے۔",
  "Updated {time}": "اپ ڈیٹ {time}", "{n} hourly readings, {source}.": "{n} گھنٹہ وار ریڈنگز، {source}۔",
  "simulated (demo)": "نقلی (ڈیمو)", "live from Open-Meteo": "Open-Meteo سے لائیو",
  "The monitor returned nothing usable this time.": "اس بار مانیٹر کو قابلِ استعمال ڈیٹا نہیں ملا۔",
  "Peaks {level} (AQI {aqi}) in the next 6 h": "اگلے 6 گھنٹوں میں زیادہ سے زیادہ {level} (اے کیو آئی {aqi})",
  "Best time outside: {from} to {to}.": "باہر جانے کا بہترین وقت: {from} سے {to} تک۔",
  "Model forecast from Open-Meteo.": "Open-Meteo کی ماڈل پیش گوئی۔", "Simulated forecast (demo).": "نقلی پیش گوئی (ڈیمو)۔",
  "No forecast": "کوئی پیش گوئی نہیں", "The forecast agent had no data this time.": "اس بار پیش گوئی ایجنٹ کے پاس ڈیٹا نہیں تھا۔",
  "{rate} µg/m³ per hour": "{rate} µg/m³ فی گھنٹہ", "sudden spike": "اچانک اضافہ",
  "Data unavailable: no valid readings": "ڈیٹا دستیاب نہیں: کوئی درست ریڈنگ نہیں",
  "No advice this time.": "اس بار کوئی مشورہ نہیں۔",
  "Plus specific advice for 5 groups, in English and Urdu.": "اس کے علاوہ 5 گروپس کے لیے خاص مشورہ، انگریزی اور اردو میں۔",
  "No alerts yet": "ابھی کوئی الرٹ نہیں", "Alerts start when the air crosses a threshold or spikes.":
    "جب ہوا حد سے بڑھے یا اچانک بگڑے تو الرٹس شروع ہوتے ہیں۔",
  "Raised on this run, at {time}.": "اسی رن میں {time} پر جاری ہوا۔",
  "Raised at {time}. No new alert on this run.": "{time} پر جاری ہوا۔ اس رن میں کوئی نیا الرٹ نہیں۔",
  "Can't reach the SmogShield server, so the live example is paused on the last values. Retrying…":
    "اسموگ شیلڈ سرور سے رابطہ نہیں، اس لیے لائیو مثال آخری اقدار پر رکی ہوئی ہے۔ دوبارہ کوشش…",
  "Can't reach the SmogShield server yet, so there is no live example. Everything above still explains how it works. Retrying…":
    "اسموگ شیلڈ سرور سے ابھی رابطہ نہیں، اس لیے لائیو مثال نہیں۔ اوپر کی تفصیل اب بھی بتاتی ہے کہ یہ کیسے کام کرتا ہے۔ دوبارہ کوشش…",
  // history
  "Alert history": "الرٹس کی ہسٹری", "Alerts": "الرٹس", "Urgency": "فوریت", "Source": "ذریعہ",
  "Every alert the Alert agent raised, newest first: when, where, how urgent, and whether it was delivered.":
    "الرٹ ایجنٹ کے جاری کردہ تمام الرٹس، نئے پہلے: کب، کہاں، کتنے فوری، اور کیا پہنچائے گئے۔",
  "No alerts match these filters.": "ان فلٹرز سے کوئی الرٹ نہیں ملا۔", "Show all alerts": "تمام الرٹس دکھائیں",
  "Shows the newest 100 alerts, which is everything the alert store keeps.": "نئے ترین 100 الرٹس دکھاتا ہے، جو الرٹ اسٹور میں محفوظ سب کچھ ہے۔",
  "Time": "وقت", "Location": "مقام", "Level": "سطح", "Message": "پیغام", "Channel": "چینل", "Delivery": "ترسیل",
  "Sent": "بھیجا گیا", "Queued": "قطار میں", "Failed": "ناکام", "Sending to Telegram": "ٹیلیگرام پر بھیجا جا رہا ہے",
  "{detail} (kept in the dashboard feed)": "{detail} (ڈیش بورڈ فیڈ میں محفوظ)", "Telegram": "ٹیلیگرام",
  "No alerts yet. Trigger a scenario on the dashboard.": "ابھی کوئی الرٹ نہیں۔ ڈیش بورڈ پر کوئی منظرنامہ چلائیں۔",
  "Showing {shown} of {all}": "{all} میں سے {shown} دکھائے جا رہے ہیں",
  "Can't reach the SmogShield server. Showing the alerts loaded earlier; retrying…":
    "اسموگ شیلڈ سرور سے رابطہ نہیں۔ پہلے لوڈ شدہ الرٹس دکھائے جا رہے ہیں؛ دوبارہ کوشش…",
  "Can't reach the SmogShield server yet. Retrying…": "اسموگ شیلڈ سرور سے ابھی رابطہ نہیں۔ دوبارہ کوشش…",
};

// Trusted, hand-written markup (never API data) for static paragraphs that contain links or emphasis
const UR_HTML = {
  footer: 'ہوا کے معیار کا ڈیٹا: <a href="https://open-meteo.com">Open-Meteo</a>، Copernicus Atmosphere Monitoring '
    + "Service کے CAMS ENSEMBLE ڈیٹا پر مبنی۔ زمرے: پاکستان کی قومی صاف ہوا پالیسی 2023۔",
  pitch: "<strong>پانچ مل کر کام کرنے والے ایجنٹس</strong> ہوا کے معیار کے خام ڈیٹا کو ریڈنگ، پیش گوئی، ہر گروپ کے لیے "
    + 'انگریزی اور <span lang="ur" class="urdu-inline">اردو</span> میں مشورے، اور الرٹس میں بدلتے ہیں، ہر چند سیکنڈ بعد۔',
  advisoryDoes: 'جائزے کو ہر گروپ کے لیے رہنمائی میں بدلتا ہے، انگریزی اور <span lang="ur" class="urdu-inline">اردو</span> میں۔',
  factModel: "<strong>ماڈل ڈیٹا، زمینی سینسر نہیں۔</strong> ریڈنگز Open-Meteo سے آتی ہیں، جو CAMS (Copernicus Atmosphere "
    + "Monitoring Service) کے ماحولیاتی ماڈل پر مبنی ہیں۔ یہ اردگرد کے علاقے کی ہوا کا اندازہ ہیں، کسی ایک گلی کا نہیں۔",
  factAqi: "<strong>اے کیو آئی گھنٹہ وار اندازہ ہے۔</strong> عدد PM2.5 اور PM10 کے لیے US EPA طریقے سے نکالا جاتا ہے، اور "
    + "دونوں میں سے بڑا لیا جاتا ہے۔ زمرے (اچھا سے شدید تک) پاکستان کی "
    + '<a href="https://mocc.gov.pk/SiteImage/Misc/files/NCAP%20(28-02-2023)%20v1.pdf" rel="noopener">قومی صاف ہوا پالیسی 2023</a>'
    + "، جدول 1 کے مطابق ہیں۔ ہم تازہ ترین گھنٹہ استعمال کرتے ہیں؛ سرکاری اے کیو آئی لمبی اوسط لیتا ہے، اس لیے دوسری سائٹس مختلف اعداد دکھا سکتی ہیں۔",
  factSim: "<strong>ڈیمو منظرنامے نقلی ہیں، اور ہمیشہ واضح۔</strong> نقلی ڈیٹا کا بینر، ہر اسکرین پر نشان، اور ہر الرٹ پر "
    + "نقلی کا ٹیگ۔ نقلی الرٹس ٹیلیگرام پر نہیں بھیجے جاتے جب تک ہم اسے آن نہ کریں۔",
  factAi: "<strong>AI کہاں ہے۔</strong> ایک لارج لینگویج ماڈل ‏(gpt-oss-20b، Groq) ہر گروہ کے لیے مشورہ لکھتا ہے "
    + "اور SmogShield سے پوچھے گئے سوالوں کا جواب انگریزی یا اردو میں دیتا ہے۔ اسے صرف موجودہ ریڈنگ، پیش گوئی، NCAP زمرہ "
    + "اور ہمارا جانچا ہوا مشورہ دکھایا جاتا ہے، اور غلط زمرہ ناموں، غلط شکل یا ناکامی والا جواب اصولوں پر مبنی مشورے سے "
    + "بدل دیا جاتا ہے۔ پیش گوئی CAMS ماحولیاتی ماڈل سے آتی ہے۔",
  factMedical: "<strong>عمومی رہنمائی، طبی مشورہ نہیں۔</strong> محتاط مشورہ، بغیر طبی دعووں، خوراک یا علاج کے۔",
  factFallback: "<strong>نقلی ڈیٹا پر متبادل۔</strong> اگر لائیو ذریعہ ناکام ہو یا 10 سیکنڈ سے زیادہ لے، تو مانیٹر واضح طور پر "
    + "نشان زدہ نقلی ڈیٹا پر منتقل ہو جاتا ہے، اور اگر وہ فائل بھی نہ ہو تو اندرونی ریڈنگ پر۔ پائپ لائن کبھی نہیں رکتی۔",
  factCache: "<strong>کیشنگ۔</strong> ہر شہر کا لائیو ڈیٹا 10 منٹ تک دوبارہ استعمال ہوتا ہے (ذریعہ ہر گھنٹے اپ ڈیٹ ہوتا ہے)، "
    + "اس لیے ہر 5 سیکنڈ بعد ریفریش تیز رہتا ہے اور مفت API کی حدود میں رہتا ہے۔",
  factCooldown: "<strong>الرٹ میں وقفہ، بار بار نہیں۔</strong> ہوا خراب ہونے پر ایک الرٹ، ایک ہی سطح پر دوبارہ نہیں؛ اچانک "
    + "اضافے پر زیادہ سے زیادہ ہر 30 منٹ میں ایک؛ یادداشت 3 گھنٹے بعد ختم۔",
  factTelegram: "<strong>ٹیلیگرام کچھ خراب نہیں کر سکتا۔</strong> پیغامات پس منظر میں 3 سیکنڈ کی حد کے ساتھ جاتے ہیں۔ ناکامی "
    + "لاگ ہوتی ہے اور الرٹ ڈیش بورڈ فیڈ میں رہتا ہے؛ بوٹ ٹوکن کبھی لاگ میں نہیں لکھا جاتا۔",
  factUnknown: "<strong>ڈیٹا نہ ہونا کبھی \"اچھا\" نہیں۔</strong> اگر کوئی درست ریڈنگ نہ آئے تو سطح \"نامعلوم\" ہوتی ہے اور مشورہ "
    + "احتیاط کا کہتا ہے۔",
};

// In Urdu, each inserted value (a time like "01:00 AM", "PM2.5 41") is wrapped in Unicode isolate marks
// (FSI ... PDI), so left-to-right fragments keep their own order inside right-to-left sentences.
const [FSI, PDI] = [String.fromCharCode(0x2068), String.fromCharCode(0x2069)];
const isolate = (text) => (LANG === "ur" ? FSI + text + PDI : String(text));

/** English text in, the current language out. {name} placeholders are filled from vars. */
function t(en, vars = {}) {
  const text = LANG === "ur" ? (UR[en] ?? en) : en;
  return text.replace(/\{(\w+)\}/g, (match, key) => {
    return key in vars ? isolate(vars[key]) : match;
  });
}
const levelLabel = (level) => t((LEVELS[level] ?? LEVELS.unknown).label);
const trendWord = (trend) => t(TREND_WORDS[trend] ?? trend);
const cityName = (city) => (LANG === "ur" && CITY_UR[city]) || city;

let languageApplied = false;
function applyLanguage() {
  document.documentElement.lang = LANG;
  document.documentElement.dir = LANG === "ur" ? "rtl" : "ltr";
  const plain = (el) => el.textContent.replace(/\s+/g, " ").trim();
  const nodes = [...document.querySelectorAll("[data-i18n]"),
                 ...(languageApplied ? [] : document.querySelectorAll("[data-i18n-init]"))];
  for (const el of nodes) {
    el.dataset.en ??= el.dataset.i18n || el.dataset.i18nInit || plain(el);
    el.textContent = t(el.dataset.en);
  }
  for (const el of document.querySelectorAll("[data-i18n-html]")) {
    el.dataset.enHtml ??= el.innerHTML;
    el.innerHTML = LANG === "ur" ? (UR_HTML[el.dataset.i18nHtml] ?? el.dataset.enHtml) : el.dataset.enHtml;
  }
  for (const el of document.querySelectorAll("[data-i18n-placeholder]")) el.placeholder = t(el.dataset.i18nPlaceholder);
  for (const b of document.querySelectorAll(".lang-switch button")) b.setAttribute("aria-pressed", String(b.dataset.lang === LANG));
  languageApplied = true;
}

function setLanguage(lang) {
  LANG = lang;
  try { localStorage.setItem(LANG_KEY, lang); } catch { /* fine: just not remembered */ }
  const params = new URLSearchParams(location.search);
  if (params.has("lang")) {  // ?lang= wins over the stored choice, so keep it in step
    params.set("lang", lang);
    history.replaceState(null, "", `?${params}`);
  }
  applyLanguage();
  document.dispatchEvent(new Event("languagechange"));  // each page re-renders its last data
}

document.addEventListener("click", (event) => {
  const button = event.target.closest(".lang-switch button");
  if (button && button.dataset.lang !== LANG) setLanguage(button.dataset.lang);
});
applyLanguage();  // scripts are deferred, so the page is parsed by now
getJSON("/api/city")
  .then((city) => { CITY_UR = city.labels_ur || {}; document.dispatchEvent(new Event("languagechange")); })
  .catch(() => { /* city names stay in English */ });
