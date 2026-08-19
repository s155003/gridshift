/* The intensity colour ramp.
 *
 * Hue here is data, not decoration. Every mark that takes a colour from this
 * file represents a carbon intensity, and nothing else in the interface uses
 * it. See DESIGN-EXCEPTIONS.md section 2.
 *
 * The stops are muted on purpose. A neon scale would read as novelty; this
 * one reads as a measurement.
 */

const CLEAN = [47, 125, 92];    // #2f7d5c
const MID = [201, 162, 39];     // #c9a227
const DIRTY = [168, 50, 50];    // #a83232

const lerp = (a, b, t) => a + (b - a) * t;

function mix(c1, c2, t) {
  return c1.map((v, i) => Math.round(lerp(v, c2[i], t)));
}

/**
 * Colour for an intensity, positioned within the range actually on screen.
 * Scaling to the visible window rather than an absolute scale matters: a
 * French day (56 gCO2/kWh average) and a Polish one (662) would otherwise
 * render as one flat colour each, hiding the very variation the page is about.
 */
export function intensityColor(value, lo, hi) {
  const span = Math.max(hi - lo, 1e-6);
  const t = Math.min(1, Math.max(0, (value - lo) / span));
  const rgb = t < 0.5 ? mix(CLEAN, MID, t * 2) : mix(MID, DIRTY, (t - 0.5) * 2);
  return `rgb(${rgb[0]} ${rgb[1]} ${rgb[2]})`;
}

/** Plain-language band for an hour, used in prose and aria labels. */
export function intensityBand(value, lo, hi) {
  const t = (value - lo) / Math.max(hi - lo, 1e-6);
  if (t < 0.25) return "clean";
  if (t < 0.5) return "fairly clean";
  if (t < 0.75) return "dirty";
  return "dirtiest";
}

export const RAMP_STOPS = [
  { label: "cleanest", color: `rgb(${CLEAN.join(" ")})` },
  { label: "", color: `rgb(${MID.join(" ")})` },
  { label: "dirtiest", color: `rgb(${DIRTY.join(" ")})` },
];
