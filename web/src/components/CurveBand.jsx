import { useMemo } from "react";
import { motion, useReducedMotion } from "motion/react";
import { intensityColor, RAMP_STOPS } from "../lib/scale.js";

/* The 48-hour curve as a bar per hour, each tinted by how dirty that hour is.
 *
 * This is the page's central argument made visible: the day is not flat, and
 * the clean hours sit somewhere specific. A reader should be able to see that
 * before reading a sentence, which is why it comes before the tool.
 *
 * Bars grow from the baseline on first view. That is the data arriving, not
 * an effect.
 */
export default function CurveBand({ times, values, height = 150, showLegend = true }) {
  const reduce = useReducedMotion();

  const { lo, hi, bars } = useMemo(() => {
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    const span = Math.max(hi - lo, 1);
    return {
      lo,
      hi,
      bars: values.map((v, i) => ({
        i,
        v,
        // Floor at 12% so the cleanest hour is still a visible mark.
        pct: 12 + ((v - lo) / span) * 88,
        color: intensityColor(v, lo, hi),
      })),
    };
  }, [values]);

  const cleanest = bars.reduce((a, b) => (b.v < a.v ? b : a), bars[0]);

  return (
    <figure className="m-0">
      <div
        className="flex items-end gap-px w-full"
        style={{ height }}
        role="img"
        aria-label={`Carbon intensity for the next ${values.length} hours, from ${lo.toFixed(0)} to ${hi.toFixed(0)} grams of CO2 per kilowatt hour. The cleanest hour is ${times[cleanest.i].toLocaleString([], { weekday: "long", hour: "2-digit" })}.`}
      >
        {/* Height is set directly and the reveal scales from the baseline, so a
            bar is at full height even if the animation never runs. Animating
            height itself meant anything below the fold stayed at zero. */}
        {bars.map((b) => (
          <motion.div
            key={b.i}
            className="flex-1 rounded-xs origin-bottom"
            style={{ background: b.color, height: `${b.pct}%` }}
            initial={reduce ? false : { scaleY: 0 }}
            whileInView={{ scaleY: 1 }}
            viewport={{ once: true, amount: 0 }}
            transition={{
              duration: 0.5,
              delay: reduce ? 0 : Math.min(b.i * 0.006, 0.3),
              ease: [0.22, 1, 0.36, 1],
            }}
            title={`${times[b.i].toLocaleString([], { weekday: "short", hour: "2-digit" })}  ${b.v.toFixed(0)} gCO2/kWh`}
          />
        ))}
      </div>

      <div className="flex justify-between items-baseline mt-1.5 text-ink-2 text-[0.72rem] tnum">
        <span>now</span>
        <span>+12h</span>
        <span>+24h</span>
        <span>+36h</span>
        <span>+48h</span>
      </div>

      {showLegend && (
        <figcaption className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 text-[0.78rem] text-ink-2">
          <span className="flex items-center gap-1.5">
            {RAMP_STOPS.map((s) => (
              <span key={s.color} className="w-5 h-2 rounded-xs" style={{ background: s.color }} />
            ))}
            <span className="ml-1">
              {lo.toFixed(0)} to {hi.toFixed(0)} gCO<sub>2</sub>/kWh
            </span>
          </span>
          <span>
            Cleanest hour is{" "}
            <b className="text-ink font-semibold">
              {times[cleanest.i].toLocaleString([], { weekday: "long", hour: "2-digit" })}
            </b>
            , at <b className="text-ink font-semibold tnum">{cleanest.v.toFixed(0)}</b>.
          </span>
        </figcaption>
      )}
    </figure>
  );
}
