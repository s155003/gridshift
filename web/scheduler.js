/* GridShift — the scheduler, ported from `gridshift/scheduler.py`.
 *
 * Same algorithms, same guarantees: prefix-sum sliding window for contiguous
 * jobs, an exact dynamic program for splittable jobs with a minimum block
 * length, and the pre-selection smoothing that counters the optimiser's curse.
 *
 * Kept deliberately free of DOM code so `tests/test_js_parity.py` can run it
 * under Node and check it against the Python implementation.
 */

export const DEFAULT_SMOOTH_HOURS = 3;
export const G_CO2_PER_CAR_KM = 170;

/** Centred moving average with edge padding. */
export function smoothForecast(x, windowHours, slotHours = 1) {
  const n = Math.round(windowHours / slotHours);
  if (n <= 1 || x.length < 2) return x.slice();
  const w = Math.min(n, x.length);
  const pad = Math.floor(w / 2);
  const padded = [];
  for (let i = 0; i < pad; i++) padded.push(x[0]);
  padded.push(...x);
  for (let i = 0; i < pad; i++) padded.push(x[x.length - 1]);

  const out = [];
  for (let i = 0; i + w <= padded.length && out.length < x.length; i++) {
    let s = 0;
    for (let k = 0; k < w; k++) s += padded[i + k];
    out.push(s / w);
  }
  while (out.length < x.length) out.push(out[out.length - 1]);
  return out;
}

function prefixSums(a) {
  const p = [0];
  for (let i = 0; i < a.length; i++) p.push(p[i] + a[i]);
  return p;
}

function contiguous(cost, lo, hi, n) {
  const p = prefixSums(cost.slice(lo, hi));
  let best = Infinity, bestK = 0;
  for (let k = 0; k + n < p.length; k++) {
    const s = p[k + n] - p[k];
    if (s < best) { best = s; bestK = k; }
  }
  return [[lo + bestK, lo + bestK + n]];
}

function mergeRuns(idx) {
  if (!idx.length) return [];
  const runs = [];
  let start = idx[0], prev = idx[0];
  for (const i of idx.slice(1)) {
    if (i === prev + 1) { prev = i; continue; }
    runs.push([start, prev + 1]);
    start = prev = i;
  }
  runs.push([start, prev + 1]);
  return runs;
}

/**
 * Cheapest set of blocks totalling `n` slots, each block >= `minBlock`.
 * minBlock === 1 reduces to "take the n cheapest slots"; otherwise an exact DP.
 */
function interruptible(cost, lo, hi, n, minBlock) {
  if (minBlock <= 1) {
    const idx = [];
    for (let i = lo; i < hi; i++) idx.push(i);
    idx.sort((a, b) => cost[a] - cost[b] || a - b);
    return mergeRuns(idx.slice(0, n).sort((a, b) => a - b));
  }

  const T = hi - lo;
  const p = prefixSums(cost.slice(lo, hi));
  const INF = Infinity;
  // f[t][r] = min cost to place r more slots using slots t..T-1.
  const f = Array.from({ length: T + 1 }, () => new Float64Array(n + 1).fill(INF));
  const choice = Array.from({ length: T + 1 }, () => new Int32Array(n + 1).fill(-1));
  for (let t = 0; t <= T; t++) f[t][0] = 0;

  for (let t = T - 1; t >= 0; t--) {
    for (let r = 1; r <= n; r++) {
      let best = f[t + 1][r], bestL = 0;      // skip this slot
      const maxL = Math.min(r, T - t);
      for (let L = minBlock; L <= maxL; L++) {
        const rem = r - L;
        if (rem !== 0 && rem < minBlock) continue;
        const cand = p[t + L] - p[t] + f[t + L][rem];
        if (cand < best) { best = cand; bestL = L; }
      }
      f[t][r] = best;
      choice[t][r] = bestL;
    }
  }
  if (!Number.isFinite(f[0][n])) throw new Error("infeasible block constraints");

  const blocks = [];
  let t = 0, r = n;
  while (r > 0 && t < T) {
    const L = choice[t][r];
    if (L <= 0) { t++; continue; }
    blocks.push([lo + t, lo + t + L]);
    t += L; r -= L;
  }

  // The DP can emit two legal blocks that happen to abut. They are one run of
  // machine time, so present them as one — otherwise the UI shows a job
  // "stopping" and "restarting" at the same instant.
  const slots = [];
  for (const [a, b] of blocks) for (let i = a; i < b; i++) slots.push(i);
  return mergeRuns(slots.sort((x, y) => x - y));
}

/**
 * @param {Date[]} times
 * @param {number[]} intensity  gCO2/kWh per slot
 * @param {{durationHours,powerKw,deadlineIndex?,interruptible?,minBlockHours?,name?}} job
 */
export function optimize(times, intensity, job, opts = {}) {
  const slotHours = opts.slotHours ?? 1;
  const smoothHours = opts.smoothHours ?? DEFAULT_SMOOTH_HOURS;

  const nSlots = Math.max(1, Math.ceil(job.durationHours / slotHours - 1e-9));
  if (nSlots > intensity.length) throw new Error("job longer than forecast");

  const energyPerSlot = job.powerKw * slotHours;
  const cost = intensity.map((v) => v * energyPerSlot);
  const selCost = smoothForecast(intensity, smoothHours, slotHours)
    .map((v) => v * energyPerSlot);

  const lo = 0;
  const hi = Math.min(
    intensity.length,
    job.deadlineIndex == null ? intensity.length : job.deadlineIndex
  );
  if (hi - lo < nSlots) throw new Error("deadline leaves too little room");

  let minBlock = Math.max(1, Math.round((job.minBlockHours ?? 1) / slotHours));
  const runs = job.interruptible
    ? interruptible(selCost, lo, hi, nSlots, Math.min(minBlock, nSlots))
    : contiguous(selCost, lo, hi, nSlots);

  const sum = (a, b) => cost.slice(a, b).reduce((s, x) => s + x, 0);
  const optimalG = runs.reduce((s, [a, b]) => s + sum(a, b), 0);
  const naiveG = sum(lo, lo + nSlots);

  // Worst and mean legal contiguous placement, for context in the UI.
  const p = prefixSums(cost.slice(lo, hi));
  let worst = -Infinity, total = 0, count = 0;
  for (let k = 0; k + nSlots < p.length; k++) {
    const s = p[k + nSlots] - p[k];
    worst = Math.max(worst, s); total += s; count++;
  }

  const energyKwh = energyPerSlot * nSlots;
  const savedG = naiveG - optimalG;
  return {
    blocks: runs.map(([a, b]) => ({
      startIndex: a, endIndex: b, start: times[a],
      end: new Date(times[b - 1].getTime() + slotHours * 3600e3),
    })),
    energyKwh,
    optimalG, naiveG, worstG: worst, meanG: count ? total / count : naiveG,
    savedG,
    savedPct: naiveG ? (100 * savedG) / naiveG : 0,
    optimalIntensity: energyKwh ? optimalG / energyKwh : 0,
    naiveIntensity: energyKwh ? naiveG / energyKwh : 0,
    carKm: savedG / G_CO2_PER_CAR_KM,
  };
}
