import { useMemo, useState } from "react";
import { motion, useReducedMotion } from "motion/react";

const W = 900, H = 240;
const PAD = { l: 42, r: 12, t: 14, b: 26 };

/* The forecast curve, with the scheduled hours marked.
 *
 * Three pieces of motion, each carrying information:
 *   the line draws once on arrival, so you can see the shape resolve
 *   the highlight bands spring when the schedule moves, so a change in the
 *     controls visibly relocates the window rather than teleporting it
 *   the deadline marker slides with the slider it belongs to
 * Hovering reads out the exact hour, which is the precision-behind-a-click
 * rule applied to a chart.
 */
export default function Chart({ times, values, blocks, deadlineIndex }) {
  const [hover, setHover] = useState(null);
  const reduce = useReducedMotion();

  const { x, y, lo, hi, path, runs } = useMemo(() => {
    const lo = Math.min(...values), hi = Math.max(...values);
    const span = Math.max(hi - lo, 1);
    const x = (i) => PAD.l + (i / (values.length - 1)) * (W - PAD.l - PAD.r);
    const y = (v) => PAD.t + (1 - (v - lo) / span) * (H - PAD.t - PAD.b);
    const path = values.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
    const runs = blocks.map((b) => ({
      key: `${b.startIndex}-${b.endIndex}`,
      x: x(b.startIndex) - (W - PAD.l - PAD.r) / values.length / 2,
      w: ((b.endIndex - b.startIndex) / values.length) * (W - PAD.l - PAD.r),
    }));
    return { x, y, lo, hi, path, runs };
  }, [values, blocks]);

  function onMove(e) {
    const box = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    const i = Math.round(((px - PAD.l) / (W - PAD.l - PAD.r)) * (values.length - 1));
    setHover(i >= 0 && i < values.length ? i : null);
  }

  return (
    <figure className="m-0">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-[240px] block touch-none"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label={`Carbon intensity for the next ${values.length} hours, ranging from ${lo.toFixed(0)} to ${hi.toFixed(0)} grams of CO2 per kilowatt hour, with the scheduled window marked`}
      >
        {[lo, (lo + hi) / 2, hi].map((v) => (
          <g key={v}>
            <line x1={PAD.l} y1={y(v)} x2={W - PAD.r} y2={y(v)} stroke="var(--color-rule)" />
            <text x={PAD.l - 6} y={y(v) + 3} textAnchor="end" className="fill-ink-2 text-[10px] tnum">
              {v.toFixed(0)}
            </text>
          </g>
        ))}

        {/* Keyed by position in the list rather than by slot range, so the same
            element persists as the window moves and can spring to it. Keying by
            range remounted a fresh rect each time, which both lost the animation
            and rendered one frame with width="undefined" before motion applied
            the animate values. x and width are given initial values for the same
            reason. */}
        {runs.map((r, i) => (
          <motion.rect
            key={i}
            y={PAD.t}
            height={H - PAD.t - PAD.b}
            fill="var(--color-accent)"
            initial={reduce ? false : { x: r.x, width: r.w, opacity: 0 }}
            animate={{ x: r.x, width: r.w, opacity: 0.14 }}
            transition={{ type: "spring", stiffness: 260, damping: 30 }}
          />
        ))}

        <motion.path
          d={path}
          fill="none"
          stroke="var(--color-ink)"
          strokeWidth={1.5}
          initial={reduce ? false : { pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.7, ease: "easeOut" }}
        />

        <motion.line
          y1={PAD.t}
          y2={H - PAD.b}
          stroke="var(--color-neg)"
          strokeDasharray="3 3"
          animate={{ x1: x(Math.min(deadlineIndex, values.length - 1)), x2: x(Math.min(deadlineIndex, values.length - 1)) }}
          transition={{ type: "spring", stiffness: 300, damping: 32 }}
        />

        {hover != null && (
          <g>
            <line x1={x(hover)} y1={PAD.t} x2={x(hover)} y2={H - PAD.b} stroke="var(--color-accent)" />
            <circle cx={x(hover)} cy={y(values[hover])} r="3" fill="var(--color-accent)" />
          </g>
        )}

        {times.map((t, i) =>
          t.getHours() % 6 === 0 ? (
            <text key={i} x={x(i)} y={H - 7} textAnchor="middle" className="fill-ink-2 text-[10px] tnum">
              {String(t.getHours()).padStart(2, "0")}
            </text>
          ) : null,
        )}
      </svg>

      <figcaption className="h-5 mt-1 text-ink-2 text-[0.78rem] tnum">
        {hover != null ? (
          <>
            {times[hover].toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}
            {" · "}
            <span className="text-ink">{values[hover].toFixed(0)}</span> gCO<sub>2</sub>/kWh
            {blocks.some((b) => hover >= b.startIndex && hover < b.endIndex) && (
              <span className="text-pos"> · scheduled</span>
            )}
          </>
        ) : (
          <span className="opacity-60">Hover the chart for any hour.</span>
        )}
      </figcaption>
    </figure>
  );
}
