import { AnimatePresence, motion } from "motion/react";
import AnimatedNumber from "./AnimatedNumber.jsx";

const fmt = (d) =>
  d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });

/* The verdict is a sentence with the figures inside it, not a wall of numbers
   above one. It also tells the truth about small savings instead of dressing
   them up, which matters because the honest answer on a flat grid is "barely
   worth it". */
function Verdict({ result, regionName, jobName }) {
  const pct = result.savedPct;

  if (pct < 0.5) {
    return (
      <>
        Starting now is already the cleanest option inside this deadline.{" "}
        {regionName} is forecast at{" "}
        <b className="tnum font-semibold">
          <AnimatedNumber value={result.naiveIntensity} />
        </b>{" "}
        gCO<sub>2</sub>/kWh across the window, with too little variation to be worth waiting for.
      </>
    );
  }

  const when = result.blocks.map((b, i) => (
    <span key={b.startIndex}>
      {i > 0 && ", then "}
      <b className="font-semibold">{fmt(b.start)}</b> to <b className="font-semibold">{fmt(b.end)}</b>
    </span>
  ));

  return (
    <>
      Run {jobName.toLowerCase()} at {when}, when {regionName} is forecast at{" "}
      <b className="tnum font-semibold">
        <AnimatedNumber value={result.optimalIntensity} />
      </b>{" "}
      rather than{" "}
      <b className="tnum font-semibold">
        <AnimatedNumber value={result.naiveIntensity} />
      </b>{" "}
      gCO<sub>2</sub>/kWh. That is{" "}
      {pct < 5 ? (
        <span className="text-neg font-semibold">
          a slim <AnimatedNumber value={pct} />% reduction
        </span>
      ) : (
        <span className="text-pos font-semibold">
          <AnimatedNumber value={pct} />% less CO<sub>2</sub>
        </span>
      )}{" "}
      for the same{" "}
      <b className="tnum font-semibold">
        <AnimatedNumber value={result.energyKwh} decimals={1} />
      </b>{" "}
      kWh of work, saving{" "}
      <b className="tnum font-semibold">
        <AnimatedNumber value={result.savedG / 1000} decimals={2} />
      </b>{" "}
      kg.
    </>
  );
}

function Cell({ label, value, unit, decimals = 0, tone = "" }) {
  return (
    <div className="py-1.5 pr-3">
      <dt className="label mb-px">{label}</dt>
      <dd className={`m-0 tnum ${tone}`}>
        <AnimatedNumber value={value} decimals={decimals} />
        <span className="text-ink-2 text-[0.78rem]"> {unit}</span>
      </dd>
    </div>
  );
}

export default function Result({ result, regionName, jobName }) {
  return (
    <>
      <p className="text-[1.02rem] m-0 mb-3.5 max-w-[70ch]">
        <Verdict result={result} regionName={regionName} jobName={jobName} />
      </p>

      <dl className="grid gap-0 border-y border-rule mb-4 grid-cols-[repeat(auto-fit,minmax(112px,1fr))]">
        <Cell label="Run now" value={result.naiveIntensity} unit="gCO2/kWh" />
        <Cell label="Shifted" value={result.optimalIntensity} unit="gCO2/kWh" />
        <Cell
          label="Reduction"
          value={result.savedPct}
          unit="%"
          tone={result.savedPct >= 5 ? "text-pos font-semibold" : ""}
        />
        <Cell label="Energy" value={result.energyKwh} unit="kWh" decimals={1} />
        <Cell label="Equivalent" value={result.carKm} unit="km not driven" />
      </dl>
    </>
  );
}

export function Windows({ blocks }) {
  return (
    <ul className="list-none p-0 mt-2.5 flex flex-wrap gap-1.5">
      <AnimatePresence mode="popLayout" initial={false}>
        {blocks.map((b) => (
          <motion.li
            key={`${b.startIndex}-${b.endIndex}`}
            layout
            initial={{ opacity: 0, y: -3 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 3 }}
            transition={{ duration: 0.18 }}
            className="rounded-xs border border-accent text-pos px-2 py-0.5 text-[0.82rem] tnum"
          >
            {fmt(b.start)} to {fmt(b.end)}
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  );
}
