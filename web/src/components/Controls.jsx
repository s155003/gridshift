import RegionSearch from "./RegionSearch.jsx";
import WorkloadSearch from "./WorkloadSearch.jsx";

function Slider({ id, label, value, onChange, min, max, step, format }) {
  return (
    <div className="mt-3">
      <label htmlFor={id} className="flex justify-between items-baseline gap-2 text-[0.8rem] text-ink-2 mb-1">
        <span>{label}</span>
        <span className="tnum text-ink">{format(value)}</span>
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(+e.target.value)}
      />
    </div>
  );
}

export default function Controls({ job, region, horizon, parsed, onJob, onRegion, onParsed }) {
  return (
    <section>
      <h2 className="label border-b border-rule pb-1 mb-3">Workload</h2>

      <WorkloadSearch horizon={horizon} parsed={parsed} onParsed={onParsed} />

      <RegionSearch value={region} onChange={onRegion} />

      {/* The sliders stay: typing gets you a sensible job, then you adjust. */}
      <details className="mt-4 border-t border-rule pt-2" open>
        <summary className="cursor-pointer label text-accent">Adjust by hand</summary>

        <Slider
          id="duration" label="Run time" min={0.5} max={24} step={0.5}
          value={job.durationHours}
          onChange={(v) => onJob({ durationHours: v })}
          format={(v) => `${v.toFixed(1)} h`}
        />
        <Slider
          id="power" label="Power draw" min={0.05} max={60} step={0.05}
          value={job.powerKw}
          onChange={(v) => onJob({ powerKw: v })}
          format={(v) => `${v.toFixed(2)} kW`}
        />
        <Slider
          id="deadline" label="Finish within" min={2} max={horizon} step={1}
          value={job.deadlineIndex}
          onChange={(v) => onJob({ deadlineIndex: v })}
          format={(v) => `${v} h`}
        />

        <label htmlFor="split" className="flex items-center gap-2 mt-4 text-[0.85rem] text-ink-2 cursor-pointer">
          <input
            id="split"
            type="checkbox"
            checked={job.interruptible}
            onChange={(e) => onJob({ interruptible: e.target.checked })}
            className="accent-accent"
          />
          Can pause and resume
        </label>
      </details>
    </section>
  );
}
