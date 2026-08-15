/* GridShift dashboard — live data, in-browser model, no backend. */

import { optimize } from "./scheduler.js";
import { predictSeries } from "./model.js";

const REGIONS = {
  GB:    { name: "Great Britain",        lat: 54.0,  lon: -2.0,   mean: 124, official: true },
  FR:    { name: "France",               lat: 46.8,  lon: 2.4,    mean: 56 },
  DE:    { name: "Germany",              lat: 51.2,  lon: 10.4,   mean: 381 },
  ES:    { name: "Spain",                lat: 40.4,  lon: -3.7,   mean: 150 },
  PL:    { name: "Poland",               lat: 52.2,  lon: 19.1,   mean: 662 },
  IE:    { name: "Ireland",              lat: 53.3,  lon: -7.7,   mean: 320 },
  CAISO: { name: "California (CAISO)",   lat: 36.8,  lon: -119.4, mean: 240 },
  ERCOT: { name: "Texas (ERCOT)",        lat: 31.0,  lon: -99.0,  mean: 400 },
  PJM:   { name: "US Mid-Atlantic (PJM)",lat: 39.8,  lon: -77.5,  mean: 350 },
  NYISO: { name: "New York (NYISO)",     lat: 42.9,  lon: -75.5,  mean: 210 },
  IN:    { name: "India",                lat: 21.0,  lon: 79.0,   mean: 713 },
  AU:    { name: "Australia (NEM)",      lat: -33.0, lon: 147.0,  mean: 550 },
  JP:    { name: "Japan",                lat: 36.2,  lon: 138.3,  mean: 490 },
  BR:    { name: "Brazil",               lat: -14.0, lon: -51.0,  mean: 120 },
};

const PRESETS = {
  ev:        { label: "EV charge",          hours: 6, kw: 7.0,  split: true,  block: 1, deadline: 14 },
  training:  { label: "ML training run",    hours: 4, kw: 0.7,  split: false, block: 1, deadline: 24 },
  dishwasher:{ label: "Dishwasher",         hours: 2, kw: 1.2,  split: false, block: 1, deadline: 12 },
  batch:     { label: "Data-centre batch",  hours: 8, kw: 50.0, split: true,  block: 2, deadline: 48 },
  heating:   { label: "Water heating",      hours: 3, kw: 3.0,  split: true,  block: 1, deadline: 12 },
};

const GB_SITES = [[57.15, -2.10], [54.05, -1.50], [52.40, -3.90], [51.30, 0.30]];
const HOURLY = "temperature_2m,wind_speed_100m,shortwave_radiation,cloud_cover";

const $ = (id) => document.getElementById(id);
const state = { region: "GB", preset: "ev", forecast: null, modelSpec: null, busy: false };

/* ---------------------------------------------------------------- data --- */

async function fetchGBOfficial() {
  const r = await fetch("https://api.carbonintensity.org.uk/intensity/" +
    new Date().toISOString().slice(0, 16) + "Z/fw48h");
  if (!r.ok) throw new Error("official feed " + r.status);
  const rows = (await r.json()).data || [];

  // Half-hourly settlement periods → hourly slots.
  const byHour = new Map();
  for (const row of rows) {
    const d = new Date(row.from);
    const v = row.intensity?.forecast;
    if (v == null) continue;
    const key = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(),
      d.getUTCDate(), d.getUTCHours())).getTime();
    if (!byHour.has(key)) byHour.set(key, []);
    byHour.get(key).push(v);
  }
  const keys = [...byHour.keys()].sort((a, b) => a - b);
  if (keys.length < 12) throw new Error("official feed too short");
  return {
    times: keys.map((k) => new Date(k)),
    values: keys.map((k) => byHour.get(k).reduce((s, x) => s + x, 0) / byHour.get(k).length),
    tier: "official",
    note: "National Grid ESO published forecast",
  };
}

function sitesAround(lat, lon, spread = 2) {
  return [[lat + spread, lon], [lat, lon - spread], [lat, lon + spread], [lat - spread, lon]];
}

async function fetchWeather(sites) {
  const results = await Promise.all(sites.map(([la, lo]) =>
    fetch(`https://api.open-meteo.com/v1/forecast?latitude=${la}&longitude=${lo}` +
      `&hourly=${HOURLY}&forecast_days=3&timezone=UTC`).then((r) => {
      if (!r.ok) throw new Error("open-meteo " + r.status);
      return r.json();
    })));
  return results.map((p) => p.hourly);
}

async function loadModel() {
  if (state.modelSpec) return state.modelSpec;
  const r = await fetch("./model.json");
  if (!r.ok) throw new Error("model.json " + r.status);
  state.modelSpec = await r.json();
  return state.modelSpec;
}

async function fetchModelled(code) {
  const reg = REGIONS[code];
  const sites = code === "GB" ? GB_SITES : sitesAround(reg.lat, reg.lon);
  const [spec, hourly] = await Promise.all([loadModel(), fetchWeather(sites)]);

  const now = Date.now() - 3600e3;
  const stamps = hourly[0].time
    .map((t, i) => ({ i, d: new Date(t + "Z") }))
    .filter(({ d }) => d.getTime() >= now)
    .slice(0, 48);

  const times = stamps.map((s) => s.d);
  const siteSeries = stamps.map(({ i }) => hourly.map((h) => ({
    windKmh: h.wind_speed_100m[i],
    solar: h.shortwave_radiation[i],
    temp: h.temperature_2m[i],
    cloud: h.cloud_cover[i],
  })));

  let values = predictSeries(spec, times, siteSeries);
  let tier = "modelled", note = "GridShift model on live weather";
  if (code !== "GB") {
    const scale = reg.mean / REGIONS.GB.mean;
    values = values.map((v) => v * scale);
    tier = "transferred";
    note = `level-calibrated ×${scale.toFixed(2)} to ${reg.name}'s published annual mean`;
  }
  return { times, values, tier, note };
}

async function getForecast(code) {
  if (REGIONS[code].official) {
    try { return await fetchGBOfficial(); }
    catch (e) { console.warn("official feed unavailable, using model:", e.message); }
  }
  return await fetchModelled(code);
}

/* ------------------------------------------------------------------ ui --- */

function jobFromControls() {
  const hours = +$("duration").value;
  const kw = +$("power").value;
  const deadline = +$("deadline").value;
  return {
    name: PRESETS[state.preset].label,
    durationHours: hours,
    powerKw: kw,
    interruptible: $("split").checked,
    minBlockHours: PRESETS[state.preset].block,
    deadlineIndex: deadline,
  };
}

function applyPreset(key) {
  const p = PRESETS[key];
  state.preset = key;
  $("duration").value = p.hours;
  $("power").value = p.kw;
  $("deadline").value = p.deadline;
  $("split").checked = p.split;
  document.querySelectorAll(".preset").forEach((b) =>
    b.classList.toggle("on", b.dataset.preset === key));
  syncLabels();
}

function syncLabels() {
  $("durationVal").textContent = `${(+$("duration").value).toFixed(1)} h`;
  $("powerVal").textContent = `${(+$("power").value).toFixed(2)} kW`;
  $("deadlineVal").textContent = `${$("deadline").value} h`;
}

function fmt(d) {
  return d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
}

function drawChart(fc, result) {
  const W = 900, H = 260, PAD = { l: 46, r: 14, t: 16, b: 28 };
  const n = fc.values.length;
  const lo = Math.min(...fc.values), hi = Math.max(...fc.values);
  const span = Math.max(hi - lo, 1);
  const x = (i) => PAD.l + (i / (n - 1)) * (W - PAD.l - PAD.r);
  const y = (v) => PAD.t + (1 - (v - lo) / span) * (H - PAD.t - PAD.b);

  const chosen = new Set();
  for (const b of result.blocks)
    for (let i = b.startIndex; i < b.endIndex; i++) chosen.add(i);

  const area = fc.values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const bars = fc.values.map((v, i) => {
    const w = (W - PAD.l - PAD.r) / n;
    const on = chosen.has(i);
    return `<rect x="${x(i) - w / 2}" y="${PAD.t}" width="${w}" height="${H - PAD.t - PAD.b}"
      fill="${on ? "var(--accent)" : "transparent"}" opacity="${on ? .18 : 0}"/>`;
  }).join("");

  const deadlineX = x(Math.min(+$("deadline").value, n - 1));
  const ticks = [lo, lo + span / 2, hi].map((v) =>
    `<g><line x1="${PAD.l}" y1="${y(v)}" x2="${W - PAD.r}" y2="${y(v)}" stroke="var(--grid)"/>
     <text x="${PAD.l - 8}" y="${y(v) + 4}" text-anchor="end" class="ax">${v.toFixed(0)}</text></g>`
  ).join("");

  const hours = fc.times.map((t, i) => t.getHours() % 6 === 0
    ? `<text x="${x(i)}" y="${H - 8}" text-anchor="middle" class="ax">${String(t.getHours()).padStart(2, "0")}</text>`
    : "").join("");

  $("chart").innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img"
         aria-label="Carbon intensity forecast with the chosen run window highlighted">
      ${ticks}${bars}
      <polyline points="${area}" fill="none" stroke="var(--line)" stroke-width="2"/>
      <line x1="${deadlineX}" y1="${PAD.t}" x2="${deadlineX}" y2="${H - PAD.b}"
            stroke="var(--warn)" stroke-dasharray="4 4"/>
      <text x="${deadlineX - 6}" y="${PAD.t + 12}" text-anchor="end" class="ax dl">deadline</text>
      ${hours}
    </svg>`;
}

function render(fc, result) {
  $("tier").textContent = fc.tier;
  $("tier").className = "tier " + fc.tier;
  $("note").textContent = fc.note;

  $("saved").textContent = `${result.savedPct.toFixed(0)}%`;
  $("savedKg").textContent = `${(result.savedG / 1000).toFixed(2)} kg CO₂ avoided`;
  $("nowVal").textContent = `${result.naiveIntensity.toFixed(0)}`;
  $("shiftVal").textContent = `${result.optimalIntensity.toFixed(0)}`;
  $("energy").textContent = `${result.energyKwh.toFixed(1)} kWh`;
  $("carkm").textContent = `${result.carKm.toFixed(0)} km`;

  $("windows").innerHTML = result.blocks
    .map((b) => `<li><span>${fmt(b.start)}</span> → <span>${fmt(b.end)}</span></li>`)
    .join("");

  $("caveat").hidden = fc.tier !== "transferred";
  drawChart(fc, result);
}

async function refresh({ refetch = false } = {}) {
  if (state.busy) return;
  state.busy = true;
  $("status").textContent = refetch ? "fetching live data…" : "";
  try {
    if (refetch || !state.forecast) state.forecast = await getForecast(state.region);
    const fc = state.forecast;
    const job = jobFromControls();
    job.deadlineIndex = Math.min(job.deadlineIndex, fc.values.length);
    if (job.durationHours > job.deadlineIndex) {
      $("status").textContent = "deadline is shorter than the job — widen it";
      return;
    }
    render(fc, optimize(fc.times, fc.values, job));
    $("status").textContent = "";
  } catch (err) {
    console.error(err);
    $("status").textContent = "could not load live data: " + err.message;
  } finally {
    state.busy = false;
  }
}

/* --------------------------------------------------------------- wiring --- */

function init() {
  const sel = $("region");
  sel.innerHTML = Object.entries(REGIONS)
    .map(([k, v]) => `<option value="${k}">${v.name}</option>`).join("");
  sel.value = state.region;

  $("presets").innerHTML = Object.entries(PRESETS)
    .map(([k, p]) => `<button class="preset" data-preset="${k}">${p.label}</button>`).join("");
  document.querySelectorAll(".preset").forEach((b) =>
    b.addEventListener("click", () => { applyPreset(b.dataset.preset); refresh(); }));

  sel.addEventListener("change", () => {
    state.region = sel.value;
    state.forecast = null;
    refresh({ refetch: true });
  });

  for (const id of ["duration", "power", "deadline"])
    $(id).addEventListener("input", () => { syncLabels(); refresh(); });
  $("split").addEventListener("change", () => refresh());

  applyPreset("ev");
  refresh({ refetch: true });
}

document.addEventListener("DOMContentLoaded", init);
