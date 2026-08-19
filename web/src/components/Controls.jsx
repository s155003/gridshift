import { REGIONS, PRESETS } from "../lib/regions.js";

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

export default function Controls({ job, region, preset, onJob, onRegion, onPreset }) {
  return (
    <section>
      <h2 className="label border-b border-rule pb-1 mb-3">Workload</h2>

      <div className="flex flex-wrap gap-1.5">
        {Object.entries(PRESETS).map(([key, p]) => {
          const on = key === preset;
          return (
            <button
              key={key}
              type="button"
              onClick={() => onPreset(key)}
              aria-pressed={on}
              className={
                "rounded-xs border px-2 py-0.5 text-[0.8rem] transition-colors duration-150 " +
                (on
                  ? "bg-accent border-accent text-white font-semibold"
                  : "bg-white border-rule text-ink-2 hover:border-accent hover:text-ink")
              }
            >
              {p.label}
            </button>
          );
        })}
      </div>

      <div className="mt-3">
        <label htmlFor="region" className="block text-[0.8rem] text-ink-2 mb-1">
          Grid region
        </label>
        <select
          id="region"
          value={region}
          onChange={(e) => onRegion(e.target.value)}
          className="w-full rounded-xs border border-rule bg-white px-2 py-1.5 text-[0.9rem] text-ink"
        >
          {Object.entries(REGIONS).map(([code, r]) => (
            <option key={code} value={code}>
              {r.name}
            </option>
          ))}
        </select>
      </div>

      <Slider
        id="duration" label="Run time" min={0.5} max={12} step={0.5}
        value={job.durationHours}
        onChange={(v) => onJob({ durationHours: v })}
        format={(v) => `${v.toFixed(1)} h`}
      />
      <Slider
        id="power" label="Power draw" min={0.05} max={50} step={0.05}
        value={job.powerKw}
        onChange={(v) => onJob({ powerKw: v })}
        format={(v) => `${v.toFixed(2)} kW`}
      />
      <Slider
        id="deadline" label="Finish within" min={2} max={48} step={1}
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
    </section>
  );
}
