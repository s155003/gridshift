/* GridShift: the trained model, running in your browser.
 *
 * `model.json` holds the raw node arrays of the gradient-boosted ensemble fit
 * in `scripts/train.py`. Everything below is a faithful port of
 * `gridshift/features.py` and the tree traversal in `gridshift/model.py`, so
 * the browser and Python produce identical predictions, and a test asserts it.
 *
 * There is no server. The page fetches a weather forecast and evaluates 400
 * decision trees client-side.
 */

export const CUT_IN = 3.5;
export const RATED = 12.5;
export const CUT_OUT = 25.0;
const HEAT_BASE_C = 15.5;
const COOL_BASE_C = 22.0;

/** Normalised turbine output in [0,1] for hub-height wind speed in m/s. */
export function turbineCurve(ms) {
  if (ms < CUT_IN || ms >= CUT_OUT) return 0;
  if (ms >= RATED) return 1;
  return (ms ** 3 - CUT_IN ** 3) / (RATED ** 3 - CUT_IN ** 3);
}

const clamp01 = (x) => Math.min(1, Math.max(0, x));
const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length;

/**
 * Build the feature record for one hour.
 * `sites` is an array of 4 objects: {windKmh, solar, temp, cloud}.
 */
export function buildFeatures(date, sites) {
  const hour = date.getUTCHours() + date.getUTCMinutes() / 60;
  const dow = (date.getUTCDay() + 6) % 7; // JS Sunday=0 → Python Monday=0
  const doy =
    Math.floor((date - Date.UTC(date.getUTCFullYear(), 0, 0)) / 86400000);

  const windMs = sites.map((s) => s.windKmh / 3.6);
  const power = windMs.map(turbineCurve);
  const solar = sites.map((s) => s.solar);
  const temp = sites.map((s) => s.temp);
  const cloud = sites.map((s) => s.cloud);

  const f = {
    hour_sin: Math.sin((2 * Math.PI * hour) / 24),
    hour_cos: Math.cos((2 * Math.PI * hour) / 24),
    dow_sin: Math.sin((2 * Math.PI * dow) / 7),
    dow_cos: Math.cos((2 * Math.PI * dow) / 7),
    doy_sin: Math.sin((2 * Math.PI * doy) / 365.25),
    doy_cos: Math.cos((2 * Math.PI * doy) / 365.25),
    is_weekend: dow >= 5 ? 1 : 0,
    is_workhours: dow < 5 && hour >= 7 && hour < 19 ? 1 : 0,
  };
  for (let i = 0; i < 4; i++) {
    f[`wind_power_${i}`] = power[i];
    f[`solar_${i}`] = solar[i] / 1000;
  }

  const solarMean = mean(solar) / 1000;
  const tempMean = mean(temp);

  f.wind_power_mean = mean(power);
  f.wind_power_min = Math.min(...power);
  f.wind_power_max = Math.max(...power);
  f.wind_power_spread = Math.max(...power) - Math.min(...power);
  f.wind_speed_mean = mean(windMs);
  f.solar_mean = solarMean;
  f.solar_max = Math.max(...solar) / 1000;
  f.cloud_mean = mean(cloud) / 100;
  f.temp_mean = tempMean;
  f.temp_spread = Math.max(...temp) - Math.min(...temp);
  f.heating_degrees = Math.max(0, HEAT_BASE_C - tempMean);
  f.cooling_degrees = Math.max(0, tempMean - COOL_BASE_C);

  f.dunkelflaute = (1 - f.wind_power_mean) * (1 - clamp01(solarMean));
  f.renew_proxy = f.wind_power_mean + 0.5 * clamp01(solarMean);
  f.stress = f.dunkelflaute * (1 + f.heating_degrees / 10);
  return f;
}

/** Evaluate the exported ensemble on one feature record. */
export function predictOne(spec, featureRecord) {
  const x = spec.features.map((n) => featureRecord[n]);
  let out = spec.baseline;
  for (const t of spec.trees) {
    let node = 0;
    while (!t.leaf[node]) {
      const v = x[t.f[node]];
      if (Number.isNaN(v)) node = t.m[node] ? t.l[node] : t.r[node];
      else node = v <= t.t[node] ? t.l[node] : t.r[node];
    }
    out += t.v[node];
  }
  return Math.max(0, out);
}

export function predictSeries(spec, times, siteSeries) {
  return times.map((d, i) => predictOne(spec, buildFeatures(d, siteSeries[i])));
}
