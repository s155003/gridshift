/* Fetching the carbon-intensity curve, in three tiers of trustworthiness.
 *
 * official    the grid operator publishes its own forecast (Great Britain)
 * modelled    our model on a live weather forecast, validated against GB truth
 * transferred the same model pointed at a grid it was never trained on, with
 *             an affine calibration to that grid's published annual average
 *
 * The tier is surfaced in the UI rather than hidden, because the third one is
 * an estimate and saying so is the honest thing to do.
 */

import { predictSeries } from "../../model.js";
import { REGIONS } from "./regions.js";

const HOURLY = "temperature_2m,wind_speed_100m,shortwave_radiation,cloud_cover";
const GB_SITES = [[57.15, -2.1], [54.05, -1.5], [52.4, -3.9], [51.3, 0.3]];

/** Four points in a cross around a location, at synoptic weather-system scale. */
function sitesAround(lat, lon, spread = 2) {
  return [[lat + spread, lon], [lat, lon - spread], [lat, lon + spread], [lat - spread, lon]];
}

async function fetchGBOfficial(signal) {
  const stamp = new Date().toISOString().slice(0, 16) + "Z";
  const r = await fetch(`https://api.carbonintensity.org.uk/intensity/${stamp}/fw48h`, { signal });
  if (!r.ok) throw new Error(`carbon intensity API returned ${r.status}`);

  // The feed is half-hourly settlement periods; the scheduler works in hours.
  const byHour = new Map();
  for (const row of (await r.json()).data ?? []) {
    const v = row.intensity?.forecast;
    if (v == null) continue;
    const d = new Date(row.from);
    const key = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(), d.getUTCHours());
    if (!byHour.has(key)) byHour.set(key, []);
    byHour.get(key).push(v);
  }
  const keys = [...byHour.keys()].sort((a, b) => a - b);
  if (keys.length < 12) throw new Error("carbon intensity feed too short to schedule against");

  return {
    times: keys.map((k) => new Date(k)),
    values: keys.map((k) => {
      const xs = byHour.get(k);
      return xs.reduce((s, x) => s + x, 0) / xs.length;
    }),
    tier: "official",
    note: "National Grid ESO published forecast",
  };
}

async function fetchWeather(sites, signal) {
  const pages = await Promise.all(
    sites.map(([la, lo]) =>
      fetch(
        `https://api.open-meteo.com/v1/forecast?latitude=${la}&longitude=${lo}` +
          `&hourly=${HOURLY}&forecast_days=3&timezone=UTC`,
        { signal },
      ).then((r) => {
        if (!r.ok) throw new Error(`weather API returned ${r.status}`);
        return r.json();
      }),
    ),
  );
  return pages.map((p) => p.hourly);
}

let modelPromise = null;

/** 614KB of tree nodes, fetched once per session and reused. */
export function loadModel(base = import.meta.env.BASE_URL) {
  if (!modelPromise) {
    modelPromise = fetch(`${base}model.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`model.json returned ${r.status}`);
        return r.json();
      })
      .catch((err) => {
        modelPromise = null; // let a later attempt retry
        throw err;
      });
  }
  return modelPromise;
}

async function fetchModelled(code, signal) {
  const region = REGIONS[code];
  const sites = code === "GB" ? GB_SITES : sitesAround(region.lat, region.lon);
  const [spec, hourly] = await Promise.all([loadModel(), fetchWeather(sites, signal)]);

  const since = Date.now() - 3600e3;
  const rows = hourly[0].time
    .map((t, i) => ({ i, d: new Date(`${t}Z`) }))
    .filter(({ d }) => d.getTime() >= since)
    .slice(0, 48);

  const times = rows.map((r) => r.d);
  const series = rows.map(({ i }) =>
    hourly.map((h) => ({
      windKmh: h.wind_speed_100m[i],
      solar: h.shortwave_radiation[i],
      temp: h.temperature_2m[i],
      cloud: h.cloud_cover[i],
    })),
  );

  let values = predictSeries(spec, times, series);
  if (code === "GB") {
    return { times, values, tier: "modelled", note: "GridShift model on live weather" };
  }

  // The model lives on Great Britain's scale. Rescaling by the ratio of annual
  // averages keeps the weather-driven shape while putting the level roughly
  // where this grid actually sits.
  const scale = region.mean / REGIONS.GB.mean;
  return {
    times,
    values: values.map((v) => v * scale),
    tier: "transferred",
    note: `level-calibrated x${scale.toFixed(2)} to ${region.name}'s published annual mean`,
  };
}

export async function getForecast(code, signal) {
  if (REGIONS[code].official) {
    try {
      return await fetchGBOfficial(signal);
    } catch (err) {
      if (err.name === "AbortError") throw err;
      console.warn("official feed unavailable, falling back to the model:", err.message);
    }
  }
  return fetchModelled(code, signal);
}
