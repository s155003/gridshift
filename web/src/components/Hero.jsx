import { motion, useReducedMotion } from "motion/react";
import { ArrowRight } from "lucide-react";
import { WordsPullUp } from "./ui/prisma-hero.jsx";
import { intensityColor } from "../lib/scale.js";
import AnimatedNumber from "./AnimatedNumber.jsx";

/* Dark cinematic hero, following PrismaHero from 21st.dev: full-bleed imagery,
 * oversized display type anchored to the bottom, a copy and CTA column on the
 * right, and WordsPullUp staggering the headline.
 *
 * Two departures from the original, both deliberate:
 *
 * The photograph is transmission towers at dusk, so the imagery is the subject
 * rather than decoration. Prisma's backdrop could have been anything.
 *
 * The live carbon curve runs along the bottom edge as a luminous strip, tinted
 * by intensity. The hero therefore still carries real data from the reader's
 * own grid rather than being purely atmospheric.
 */

// Resolved from Unsplash and verified reachable rather than guessed.
// "Photo of truss towers", Matthew Henry. unsplash.com/photos/yETqkLnhsUI
const BACKDROP =
  "https://images.unsplash.com/photo-1473341304170-971dccb5ac1e?w=1920&q=72&fm=jpg&fit=crop";

const CREAM = "#E1E0CC";

export default function Hero({ forecast, regionName, onStart }) {
  const reduce = useReducedMotion();

  const stats = (() => {
    if (!forecast) return null;
    const v = forecast.values;
    const lo = Math.min(...v);
    const hi = Math.max(...v);
    const now = v[0];
    const bestIdx = v.indexOf(lo);
    return { lo, hi, now, bestIdx, cut: now > 0 ? (100 * (now - lo)) / now : 0, when: forecast.times[bestIdx] };
  })();

  const rise = reduce
    ? {}
    : {
        initial: { y: 20, opacity: 0 },
        animate: { y: 0, opacity: 1 },
        transition: { duration: 0.8, ease: [0.16, 1, 0.3, 1] },
      };

  return (
    <section className="relative mb-2">
      <div className="relative h-[88vh] min-h-[560px] w-full overflow-hidden bg-ink">
        <img
          src={BACKDROP}
          alt="High-voltage transmission towers silhouetted against a dusk sky"
          className="absolute inset-0 h-full w-full object-cover"
          loading="eager"
          fetchPriority="high"
        />

        {/* Scrim. Functional rather than decorative: display type has to stay
            legible over a photograph whose brightness we do not control. */}
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "linear-gradient(to bottom, rgba(8,10,12,0.55) 0%, rgba(8,10,12,0.25) 35%, rgba(8,10,12,0.88) 100%)",
          }}
        />

        {/* Live carbon curve along the bottom edge. The hero still carries data. */}
        {forecast && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex h-16 items-end gap-px px-1 opacity-90">
            {forecast.values.map((v, i) => {
              const pct = 14 + ((v - stats.lo) / Math.max(stats.hi - stats.lo, 1)) * 86;
              return (
                <motion.div
                  key={i}
                  className="flex-1 origin-bottom"
                  style={{ background: intensityColor(v, stats.lo, stats.hi), height: `${pct}%` }}
                  initial={reduce ? false : { scaleY: 0 }}
                  animate={{ scaleY: 1 }}
                  transition={{
                    duration: 0.7,
                    delay: reduce ? 0 : 0.5 + Math.min(i * 0.008, 0.4),
                    ease: [0.16, 1, 0.3, 1],
                  }}
                />
              );
            })}
          </div>
        )}

        {/* Content, anchored to the bottom as in the original */}
        <div className="absolute inset-x-0 bottom-0 px-5 pb-20 sm:px-8 md:px-10">
          <div className="mx-auto max-w-[1060px]">
            <motion.p {...rise} className="label mb-3" style={{ color: "rgba(225,224,204,0.65)" }}>
              GridShift
            </motion.p>

            <div className="grid grid-cols-12 items-end gap-6">
              <div className="col-span-12 lg:col-span-7">
                <h1
                  className="display m-0 leading-[0.88] tracking-[-0.04em] text-[12vw] sm:text-[10vw] lg:text-[6.4vw]"
                  style={{ color: CREAM }}
                  aria-label="Run it when the grid is clean."
                >
                  <span aria-hidden="true">
                    <WordsPullUp text="Run it when the grid is" />{" "}
                    <span style={{ color: "#8fd3b0" }}>
                      <WordsPullUp text="clean." />
                    </span>
                  </span>
                </h1>
              </div>

              <div className="col-span-12 flex flex-col gap-5 lg:col-span-5 lg:pb-3">
                <motion.p
                  {...rise}
                  transition={{ ...rise.transition, delay: reduce ? 0 : 0.5 }}
                  className="text-[0.95rem] sm:text-base"
                  style={{ color: "rgba(225,224,204,0.78)", lineHeight: 1.45 }}
                >
                  Electricity is far dirtier at some hours than others. An EV charging overnight,
                  a dishwasher, a training run: all of them have a deadline, not a start time.
                  Move them into the clean hours and the same work emits less CO<sub>2</sub>.
                </motion.p>

                {stats && (
                  <motion.dl
                    {...rise}
                    transition={{ ...rise.transition, delay: reduce ? 0 : 0.6 }}
                    className="m-0 grid grid-cols-3 gap-3 border-t pt-3"
                    style={{ borderColor: "rgba(225,224,204,0.25)" }}
                  >
                    {[
                      { k: "Now", v: stats.now, tone: CREAM },
                      {
                        k: stats.when.toLocaleString([], { weekday: "short", hour: "2-digit" }),
                        v: stats.lo,
                        tone: "#8fd3b0",
                      },
                      { k: "Avoidable", v: stats.cut, tone: "#8fd3b0", suffix: "%" },
                    ].map((s) => (
                      <div key={s.k}>
                        <dt className="label mb-1" style={{ color: "rgba(225,224,204,0.6)" }}>
                          {s.k}
                        </dt>
                        <dd className="m-0 text-[1.25rem] tnum leading-none" style={{ color: s.tone }}>
                          <AnimatedNumber value={s.v} />
                          {s.suffix}
                        </dd>
                      </div>
                    ))}
                  </motion.dl>
                )}

                <motion.button
                  {...rise}
                  transition={{ ...rise.transition, delay: reduce ? 0 : 0.7 }}
                  type="button"
                  onClick={onStart}
                  className="group inline-flex items-center gap-2 self-start rounded-full py-1 pl-5 pr-1 text-sm font-semibold text-black transition-all hover:gap-3 sm:text-base"
                  style={{ background: CREAM }}
                >
                  Schedule something on your grid
                  <span className="flex h-9 w-9 items-center justify-center rounded-full bg-black transition-transform group-hover:scale-110 sm:h-10 sm:w-10">
                    <ArrowRight className="h-4 w-4" style={{ color: CREAM }} />
                  </span>
                </motion.button>
              </div>
            </div>
          </div>
        </div>

        {/* Sits above the curve strip rather than colliding with it. */}
        <p
          className="absolute right-3 text-[0.6rem] z-10"
          style={{ bottom: "4.5rem", color: "rgba(225,224,204,0.5)" }}
        >
          Photo: Matthew Henry / Unsplash
        </p>
      </div>

      {stats && (
        <p className="mx-auto max-w-[1060px] px-5 pt-2 text-[0.75rem] text-ink-2">
          The strip along the bottom edge is the next 48 hours in {regionName}, coloured by
          carbon intensity.{" "}
          {forecast.tier === "official"
            ? "Published by the grid operator."
            : forecast.tier === "modelled"
              ? "Forecast by GridShift's model on live weather."
              : "Estimated by GridShift's model on live weather, calibrated to this grid's published annual average."}
        </p>
      )}
    </section>
  );
}
