import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";

import { optimize } from "../scheduler.js";
import { getForecast } from "./lib/forecast.js";
import { PRESETS, REGIONS, TIER_COPY } from "./lib/regions.js";
import Controls from "./components/Controls.jsx";
import Chart from "./components/Chart.jsx";
import Result, { Windows } from "./components/Result.jsx";
import ForecastTable from "./components/ForecastTable.jsx";

const TIER_CLASS = {
  official: "border-pos text-pos",
  modelled: "border-accent text-accent",
  transferred: "border-neg text-neg",
};

function presetToJob(key) {
  const p = PRESETS[key];
  return {
    name: p.label,
    durationHours: p.hours,
    powerKw: p.kw,
    interruptible: p.split,
    minBlockHours: p.block,
    deadlineIndex: p.deadline,
  };
}

export default function App() {
  const [region, setRegion] = useState("GB");
  const [preset, setPreset] = useState("ev");
  const [job, setJob] = useState(() => presetToJob("ev"));
  const [forecast, setForecast] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const abortRef = useRef(null);

  useEffect(() => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setLoading(true);
    setError(null);
    getForecast(region, ctrl.signal)
      .then((fc) => {
        if (!ctrl.signal.aborted) setForecast(fc);
      })
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });

    return () => ctrl.abort();
  }, [region]);

  const updateJob = useCallback((patch) => setJob((j) => ({ ...j, ...patch })), []);
  const applyPreset = useCallback((key) => {
    setPreset(key);
    setJob(presetToJob(key));
  }, []);

  // The schedule is derived state. Recomputing on every control change keeps
  // one source of truth and costs microseconds even for the 48-slot DP.
  const { result, scheduleError } = useMemo(() => {
    if (!forecast) return { result: null, scheduleError: null };
    const bounded = { ...job, deadlineIndex: Math.min(job.deadlineIndex, forecast.values.length) };
    if (bounded.durationHours > bounded.deadlineIndex) {
      return { result: null, scheduleError: "The deadline is shorter than the job. Widen it." };
    }
    try {
      return { result: optimize(forecast.times, forecast.values, bounded, { slotHours: 1 }), scheduleError: null };
    } catch (err) {
      return { result: null, scheduleError: err.message };
    }
  }, [forecast, job]);

  const regionName = REGIONS[region].name;
  const notice = error ?? scheduleError;

  return (
    <div className="max-w-[1060px] mx-auto px-5 pt-6 pb-14">
      <header className="flex items-baseline justify-between gap-3.5 flex-wrap border-b-2 border-ink pb-2">
        <h1 className="text-[1.25rem] font-bold tracking-[-0.01em] m-0">GridShift</h1>
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={forecast?.tier ?? "loading"}
            initial={{ opacity: 0, y: -2 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 2 }}
            transition={{ duration: 0.16 }}
            title={TIER_COPY[forecast?.tier] ?? ""}
            className={
              "label rounded-xs border px-2 py-0.5 " +
              (TIER_CLASS[forecast?.tier] ?? "border-rule text-ink-2")
            }
          >
            {loading ? "loading" : (forecast?.tier ?? "unavailable")}
          </motion.span>
        </AnimatePresence>
      </header>

      <p className="text-ink-2 mt-2.5 mb-5 max-w-[64ch]">
        Grid carbon intensity moves by the hour with wind, sun and demand. GridShift forecasts
        the next 48 hours and finds the lowest-emission window for a job that has a deadline
        rather than a start time.
      </p>

      <div className="grid gap-6 items-start grid-cols-1 md:grid-cols-[266px_1fr]">
        <Controls
          job={job}
          region={region}
          preset={preset}
          onJob={updateJob}
          onRegion={setRegion}
          onPreset={applyPreset}
        />

        <section>
          <h2 className="label border-b border-rule pb-1 mb-3">Lowest-carbon schedule</h2>

          {notice && (
            <p role="status" className="text-neg text-[0.85rem] mb-3">
              {notice}
            </p>
          )}

          {!forecast || !result ? (
            <div className="text-ink-2 text-[0.9rem] py-6" role="status">
              {loading ? `Fetching the live forecast for ${regionName}.` : "No schedule available."}
            </div>
          ) : (
            <>
              <Result result={result} regionName={regionName} jobName={job.name} />
              <Chart
                times={forecast.times}
                values={forecast.values}
                blocks={result.blocks}
                deadlineIndex={Math.min(job.deadlineIndex, forecast.values.length)}
              />
              <Windows blocks={result.blocks} />
              <p className="text-ink-2 text-[0.78rem] mt-2">{forecast.note}</p>

              <AnimatePresence>
                {forecast.tier === "transferred" && (
                  <motion.p
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden mt-3.5 border-l-2 border-neg pl-3 text-[0.85rem] text-ink-2"
                  >
                    This region publishes no open carbon-intensity feed. The curve is the Great
                    Britain model applied to this region&apos;s live weather and rescaled to its
                    published annual average. Read the shape, which is when the clean hours fall,
                    as the useful part. Treat the level as an estimate.
                  </motion.p>
                )}
              </AnimatePresence>

              <ForecastTable
                times={forecast.times}
                values={forecast.values}
                blocks={result.blocks}
              />
            </>
          )}
        </section>
      </div>

      <footer className="mt-8 border-t border-rule pt-3 text-ink-2 text-[0.85rem] max-w-[74ch]">
        <p className="mb-2">
          <b className="text-ink">Where the numbers come from.</b> Great Britain is one of the few
          grids that publishes an open 48-hour carbon-intensity forecast, and GridShift uses it
          directly where it exists.
        </p>
        <p className="mb-2">
          Everywhere else the page runs a gradient-boosted model in your browser against a live
          weather forecast. It was trained on 8,640 hours of real GB grid data paired with
          reanalysis weather. 400 trees, evaluated client-side. There is no backend.
        </p>
        <p className="mb-2">
          The scheduler is deterministic: a sliding window for jobs that must run in one block, and
          an exact dynamic program for splittable jobs with a minimum block length. It smooths the
          forecast before choosing hours, which counters the optimiser&apos;s curse, where picking
          the cheapest individual hours systematically selects the hours the model most
          under-predicts.
        </p>
        <p className="mb-0">
          Data from the{" "}
          <a className="text-accent" href="https://carbonintensity.org.uk" rel="noopener">
            National Grid ESO Carbon Intensity API
          </a>{" "}
          and{" "}
          <a className="text-accent" href="https://open-meteo.com" rel="noopener">
            Open-Meteo
          </a>
          , both free and key-less. Source, full evaluation and limitations:{" "}
          <a className="text-accent" href="https://github.com/s155003/gridshift" rel="noopener">
            github.com/s155003/gridshift
          </a>
          .
        </p>
      </footer>
    </div>
  );
}
