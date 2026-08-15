/* End-to-end smoke test of the dashboard's data path, without a browser.
 *
 * Fetches a live weather forecast, runs the exported trees, and schedules a
 * job — exactly what `app.js` does, minus the DOM. Run with:
 *
 *     node web/smoke.mjs
 */

import { readFileSync } from "node:fs";
import { buildFeatures, predictSeries } from "./model.js";
import { optimize } from "./scheduler.js";

const HOURLY = "temperature_2m,wind_speed_100m,shortwave_radiation,cloud_cover";
const SITES = [[38.8, -119.4], [36.8, -121.4], [36.8, -117.4], [34.8, -119.4]];
const GB_MEAN = 124, CAISO_MEAN = 240;

const spec = JSON.parse(readFileSync(new URL("./model.json", import.meta.url)));
console.log(`model: ${spec.n_trees} trees, ${spec.features.length} features`);
console.log(`trained on ${spec.trained_on.rows} rows ` +
  `(${spec.trained_on.start.slice(0, 10)} → ${spec.trained_on.end.slice(0, 10)})`);

const hourly = await Promise.all(SITES.map(([la, lo]) =>
  fetch(`https://api.open-meteo.com/v1/forecast?latitude=${la}&longitude=${lo}` +
    `&hourly=${HOURLY}&forecast_days=3&timezone=UTC`).then((r) => r.json())
    .then((p) => p.hourly)));

const now = Date.now() - 3600e3;
const stamps = hourly[0].time
  .map((t, i) => ({ i, d: new Date(t + "Z") }))
  .filter(({ d }) => d.getTime() >= now)
  .slice(0, 48);

const times = stamps.map((s) => s.d);
const series = stamps.map(({ i }) => hourly.map((h) => ({
  windKmh: h.wind_speed_100m[i], solar: h.shortwave_radiation[i],
  temp: h.temperature_2m[i], cloud: h.cloud_cover[i],
})));

const scale = CAISO_MEAN / GB_MEAN;
const values = predictSeries(spec, times, series).map((v) => v * scale);

console.log(`\nCAISO, next ${values.length}h (transferred, ×${scale.toFixed(2)}):`);
console.log(`  range ${Math.min(...values).toFixed(0)}–${Math.max(...values).toFixed(0)} gCO2/kWh`);

const sanity = values.every((v) => Number.isFinite(v) && v > 0 && v < 2000);
console.log(`  all values finite and plausible: ${sanity ? "yes" : "NO"}`);

// A feature record must contain every name the model expects.
const f = buildFeatures(times[0], series[0]);
const missing = spec.features.filter((n) => !(n in f) || !Number.isFinite(f[n]));
console.log(`  missing/non-finite features: ${missing.length ? missing.join(", ") : "none"}`);

for (const job of [
  { name: "EV charge", durationHours: 6, powerKw: 7, interruptible: true, minBlockHours: 1, deadlineIndex: 14 },
  { name: "DC batch", durationHours: 8, powerKw: 50, interruptible: true, minBlockHours: 2, deadlineIndex: 48 },
  { name: "ML training", durationHours: 4, powerKw: 0.7, interruptible: false, minBlockHours: 1, deadlineIndex: 24 },
]) {
  const r = optimize(times, values, job, { slotHours: 1 });
  const w = r.blocks.map((b) =>
    `${b.start.toISOString().slice(11, 16)}–${b.end.toISOString().slice(11, 16)}`).join(", ");
  console.log(`\n  ${job.name}: ${w}`);
  console.log(`    ${r.naiveIntensity.toFixed(0)} → ${r.optimalIntensity.toFixed(0)} gCO2/kWh` +
    `  (−${r.savedPct.toFixed(0)}%, ${(r.savedG / 1000).toFixed(2)} kg saved)`);
}

if (!sanity || missing.length) {
  console.error("\nSMOKE TEST FAILED");
  process.exit(1);
}
console.log("\nSMOKE TEST PASSED");
