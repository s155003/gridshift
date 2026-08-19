import { motion, useReducedMotion } from "motion/react";
import AnimatedNumber from "./AnimatedNumber.jsx";

/* The hero has one job: make a stranger understand the product before they
 * scroll. It states the problem in the reader's own terms, then backs it with
 * a live figure from their grid rather than a claim.
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
    return {
      lo, hi, now, bestIdx,
      ratio: hi / Math.max(lo, 1),
      cut: now > 0 ? (100 * (now - lo)) / now : 0,
      when: forecast.times[bestIdx],
    };
  })();

  const rise = reduce
    ? {}
    : {
        initial: { opacity: 0, y: 16 },
        animate: { opacity: 1, y: 0 },
        transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] },
      };

  return (
    <header className="pt-10 pb-2">
      <motion.p {...rise} className="label mb-4">
        GridShift
      </motion.p>

      <motion.h1
        {...rise}
        transition={{ ...rise.transition, delay: reduce ? 0 : 0.05 }}
        className="display text-[2.3rem] md:text-[3.4rem] m-0 max-w-[17ch]"
      >
        Your dishwasher does not care when it runs.
        <span className="text-accent"> The grid does.</span>
      </motion.h1>

      <motion.p
        {...rise}
        transition={{ ...rise.transition, delay: reduce ? 0 : 0.12 }}
        className="mt-6 text-[1.05rem] max-w-[56ch] text-ink-2"
      >
        Electricity is far dirtier at some hours than others, depending on wind,
        sun and demand. An EV charging overnight, a dishwasher, a model training
        run: all of them have a <b className="text-ink font-semibold">deadline</b>,
        not a start time. Move them into the clean hours and the same work emits
        less CO<sub>2</sub>, with no new hardware and nothing else changed.
      </motion.p>

      {stats && (
        <motion.div
          {...rise}
          transition={{ ...rise.transition, delay: reduce ? 0 : 0.2 }}
          className="mt-8 border-y border-rule py-4 flex flex-wrap gap-x-10 gap-y-4"
        >
          <div>
            <p className="label mb-1">{regionName}, right now</p>
            <p className="m-0 text-[1.5rem] tnum">
              <AnimatedNumber value={stats.now} />
              <span className="text-ink-2 text-[0.8rem]"> gCO2/kWh</span>
            </p>
          </div>
          <div>
            <p className="label mb-1">
              Cleanest hour, {stats.when.toLocaleString([], { weekday: "short", hour: "2-digit" })}
            </p>
            <p className="m-0 text-[1.5rem] tnum text-pos">
              <AnimatedNumber value={stats.lo} />
              <span className="text-ink-2 text-[0.8rem]"> gCO2/kWh</span>
            </p>
          </div>
          <div>
            <p className="label mb-1">Waiting for it saves</p>
            <p className="m-0 text-[1.5rem] tnum text-pos">
              <AnimatedNumber value={stats.cut} />
              <span className="text-ink-2 text-[0.8rem]">% of the CO2</span>
            </p>
          </div>
        </motion.div>
      )}

      <motion.button
        {...rise}
        transition={{ ...rise.transition, delay: reduce ? 0 : 0.26 }}
        type="button"
        onClick={onStart}
        className="mt-7 rounded-xs border border-ink bg-ink text-white px-4 py-2 text-[0.9rem] font-semibold transition-colors duration-150 hover:bg-accent hover:border-accent"
      >
        Schedule something on your grid
      </motion.button>
    </header>
  );
}
