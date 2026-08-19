import { motion, useReducedMotion } from "motion/react";
import { ArrowRight } from "lucide-react";
import { WordsPullUp } from "./ui/prisma-hero.jsx";
import { intensityColor } from "../lib/scale.js";
import AnimatedNumber from "./AnimatedNumber.jsx";

/* The hero borrows PrismaHero's structure from 21st.dev: oversized display
 * type, content anchored to the bottom, a full-bleed backdrop running behind
 * it, and a word-by-word arrival on the headline via its WordsPullUp.
 *
 * What it does not borrow is the stock video. Prisma's backdrop is decorative
 * footage; GridShift already has something with more claim to the space, which
 * is the live carbon curve for the reader's own grid. Same visual weight,
 * except the moving thing behind the headline is the argument itself.
 */
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
    <section className="relative min-h-[86vh] flex flex-col justify-end pb-6 pt-16">
      {/* Backdrop: the live forecast, full bleed behind the type. */}
      {forecast && (
        <div
          className="pointer-events-none absolute inset-x-0 bottom-0 top-24 flex items-end gap-px opacity-[0.22]"
          aria-hidden="true"
        >
          {forecast.values.map((v, i) => {
            const pct = 8 + ((v - stats.lo) / Math.max(stats.hi - stats.lo, 1)) * 92;
            return (
              <motion.div
                key={i}
                className="flex-1 origin-bottom rounded-xs"
                style={{ background: intensityColor(v, stats.lo, stats.hi), height: `${pct}%` }}
                initial={reduce ? false : { scaleY: 0 }}
                animate={{ scaleY: 1 }}
                transition={{ duration: 0.7, delay: reduce ? 0 : Math.min(i * 0.008, 0.4), ease: [0.16, 1, 0.3, 1] }}
              />
            );
          })}
        </div>
      )}

      <div className="relative">
        <motion.p {...rise} className="label mb-5">
          GridShift
        </motion.p>

        <h1
          className="display m-0 leading-[0.86] tracking-[-0.04em] text-[13vw] md:text-[9.5vw] lg:text-[8.2vw]"
          aria-label="Run it when the grid is clean."
        >
          <span aria-hidden="true">
            <WordsPullUp text="Run it when the" />
            <span className="text-accent">
              <WordsPullUp text=" grid is clean." />
            </span>
          </span>
        </h1>

        <div className="mt-9 grid grid-cols-12 items-end gap-5">
          <motion.div
            {...rise}
            transition={{ ...rise.transition, delay: reduce ? 0 : 0.45 }}
            className="col-span-12 lg:col-span-7"
          >
            <p className="text-[1.02rem] max-w-[54ch] text-ink-2">
              Electricity is far dirtier at some hours than others, depending on wind, sun and
              demand. An EV charging overnight, a dishwasher, a model training run: all of them
              have a <b className="text-ink font-semibold">deadline</b>, not a start time. Move
              them into the clean hours and the same work emits less CO<sub>2</sub>, with no new
              hardware and nothing else changed.
            </p>

            <button
              type="button"
              onClick={onStart}
              className="group mt-6 inline-flex items-center gap-2 rounded-xs border border-ink bg-ink py-1.5 pl-4 pr-1.5 text-[0.92rem] font-semibold text-white transition-all hover:gap-3 hover:bg-accent hover:border-accent"
            >
              Schedule something on your grid
              <span className="flex h-7 w-7 items-center justify-center rounded-xs bg-white/15 transition-transform group-hover:translate-x-0.5">
                <ArrowRight className="h-3.5 w-3.5" />
              </span>
            </button>
          </motion.div>

          {stats && (
            <motion.dl
              {...rise}
              transition={{ ...rise.transition, delay: reduce ? 0 : 0.55 }}
              className="col-span-12 lg:col-span-5 m-0 border-t border-ink pt-3 grid grid-cols-3 gap-3"
            >
              <div>
                <dt className="label mb-1">Now</dt>
                <dd className="m-0 text-[1.35rem] tnum leading-none">
                  <AnimatedNumber value={stats.now} />
                </dd>
              </div>
              <div>
                <dt className="label mb-1">
                  {stats.when.toLocaleString([], { weekday: "short", hour: "2-digit" })}
                </dt>
                <dd className="m-0 text-[1.35rem] tnum leading-none text-pos">
                  <AnimatedNumber value={stats.lo} />
                </dd>
              </div>
              <div>
                <dt className="label mb-1">Avoidable</dt>
                <dd className="m-0 text-[1.35rem] tnum leading-none text-pos">
                  <AnimatedNumber value={stats.cut} />%
                </dd>
              </div>
              <p className="col-span-3 m-0 text-[0.75rem] text-ink-2">
                gCO<sub>2</sub>/kWh in {regionName}, live from the grid operator.
              </p>
            </motion.dl>
          )}
        </div>
      </div>
    </section>
  );
}
