import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";

import { optimize } from "../scheduler.js";
import { getForecast } from "./lib/forecast.js";
import { REGIONS, REGION_COUNT, TIER_COPY } from "./lib/regions.js";
import Controls from "./components/Controls.jsx";
import Chart from "./components/Chart.jsx";
import Result, { Windows } from "./components/Result.jsx";
import ForecastTable from "./components/ForecastTable.jsx";
import Section from "./components/Section.jsx";
import Hero from "./components/Hero.jsx";
import CurveBand from "./components/CurveBand.jsx";
import Evidence from "./components/Evidence.jsx";

const TIER_CLASS = {
  official: "border-pos text-pos",
  modelled: "border-accent text-accent",
  transferred: "border-neg text-neg",
};

const HORIZON = 48;

export default function App() {
  const [region, setRegion] = useState("GB");
  const [parsed, setParsed] = useState(null);
  const [job, setJob] = useState({
    name: "EV charge", durationHours: 6, powerKw: 7,
    interruptible: true, minBlockHours: 1, deadlineIndex: 14,
  });
  const [forecast, setForecast] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const abortRef = useRef(null);
  const toolRef = useRef(null);

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
  const handleParsed = useCallback((result) => {
    setParsed(result);
    setJob(result.job);
  }, []);

  const { result, scheduleError } = useMemo(() => {
    if (!forecast) return { result: null, scheduleError: null };
    const bounded = { ...job, deadlineIndex: Math.min(job.deadlineIndex, forecast.values.length) };
    if (bounded.durationHours > bounded.deadlineIndex) {
      return { result: null, scheduleError: "The deadline is shorter than the job. Widen it." };
    }
    try {
      return {
        result: optimize(forecast.times, forecast.values, bounded, { slotHours: 1 }),
        scheduleError: null,
      };
    } catch (err) {
      return { result: null, scheduleError: err.message };
    }
  }, [forecast, job]);

  const regionName = REGIONS[region].name;
  const notice = error ?? scheduleError;

  return (
    <>
      {/* The hero sits outside the content column so it can run edge to edge. */}
      <Hero
        forecast={forecast}
        regionName={regionName}
        onStart={() => toolRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })}
      />

      <div className="max-w-[1060px] mx-auto px-5 pb-20">
        <Section
        label="The problem"
        title="A day on the grid is not flat."
        lede={
          forecast
            ? `Every bar is one hour of ${regionName}'s next two days, coloured by how much CO2 each kilowatt-hour carries. Green hours are clean, red hours are dirty. Nothing about the electricity changes, only when you draw it.`
            : "Loading the next two days."
        }
      >
        {forecast ? (
          <CurveBand times={forecast.times} values={forecast.values} />
        ) : (
          <div className="h-[150px] flex items-end gap-px" aria-hidden="true">
            {Array.from({ length: 48 }, (_, i) => (
              <div key={i} className="flex-1 bg-rule-2 rounded-xs" style={{ height: "30%" }} />
            ))}
          </div>
        )}
      </Section>

      <div ref={toolRef}>
        <Section
          label="The tool"
          title="Tell it what you are running."
          lede={`Type what you are running and GridShift works out the rest. It then finds the lowest-emission window that still finishes in time, on a live forecast for any of ${REGION_COUNT} grid regions.`}
        >
          <div className="flex items-center gap-2 mb-5">
            <span className="label">Forecast source</span>
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
          </div>

          <div className="grid gap-6 items-start grid-cols-1 md:grid-cols-[266px_1fr]">
            <Controls
              job={job}
              region={region}
              horizon={HORIZON}
              parsed={parsed}
              onJob={updateJob}
              onRegion={setRegion}
              onParsed={handleParsed}
            />

            <div>
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
                        This region publishes no open carbon-intensity feed. The curve is the
                        Great Britain model applied to this region&apos;s live weather and
                        rescaled to its published annual average. Read the shape, which is when
                        the clean hours fall, as the useful part. Treat the level as an estimate.
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
            </div>
          </div>
        </Section>
      </div>

      <Section
        label="The evidence"
        title="Does it actually work?"
        lede="Trained on a year of real grid data, then measured against what the grid really did. The weak results are here alongside the strong ones."
      >
        <Evidence />
      </Section>

      <Section label="How it works" title="Weather, not a carbon API.">
        <div className="grid gap-6 md:grid-cols-2 text-ink-2 text-[0.9rem] max-w-none">
          <div className="space-y-3">
            <p className="m-0">
              Great Britain is one of very few grids that publishes an open 48-hour
              carbon-intensity forecast, and GridShift uses it directly where it exists.
            </p>
            <p className="m-0">
              Almost nowhere else does. California, Texas, India and Australia do not. So for
              everywhere else this page runs a gradient-boosted model in your browser against a
              live weather forecast. 400 trees, evaluated client-side. There is no backend.
            </p>
          </div>
          <div className="space-y-3">
            <p className="m-0">
              The scheduler is deterministic: a sliding window for jobs that must run in one
              block, and an exact dynamic program for splittable jobs with a minimum block
              length. No language model computes any number you see here.
            </p>
            <p className="m-0">
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
          </div>
        </div>
        </Section>
      </div>
    </>
  );
}
