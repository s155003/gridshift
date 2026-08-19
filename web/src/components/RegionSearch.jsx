import { useMemo, useRef, useState } from "react";
import { Globe } from "lucide-react";
import { REGIONS, REGION_COUNT, searchRegions } from "../lib/regions.js";

/* 214 regions is far too many for a dropdown, so this is a combobox: type to
 * filter, accent-insensitive, keyboard navigable. */
export default function RegionSearch({ value, onChange }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef(null);

  const results = useMemo(() => searchRegions(query, 40), [query]);
  const current = REGIONS[value];

  function choose(code) {
    onChange(code);
    setQuery("");
    setOpen(false);
    setActive(0);
  }

  function onKeyDown(e) {
    if (!open && (e.key === "ArrowDown" || e.key === "Enter")) {
      setOpen(true);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (results[active]) choose(results[active].code);
    } else if (e.key === "Escape") {
      setOpen(false);
      setQuery("");
    }
  }

  return (
    <div className="relative mt-3" ref={boxRef}>
      <label htmlFor="region" className="label mb-1.5 block">
        Grid region
      </label>
      <div className="flex items-center gap-2 rounded-xs border border-rule bg-white px-2.5 py-1.5 focus-within:border-accent">
        <Globe className="h-4 w-4 shrink-0 text-ink-2" aria-hidden="true" />
        <input
          id="region"
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls="region-list"
          aria-autocomplete="list"
          value={open ? query : (current?.name ?? "")}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            setActive(0);
          }}
          onFocus={() => {
            setOpen(true);
            setQuery("");
          }}
          onBlur={() => window.setTimeout(() => setOpen(false), 120)}
          onKeyDown={onKeyDown}
          placeholder={`Search ${REGION_COUNT} regions`}
          autoComplete="off"
          className="w-full bg-transparent text-[0.9rem] text-ink outline-none placeholder:text-ink-2/60"
        />
      </div>

      {open && (
        <ul
          id="region-list"
          role="listbox"
          className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-xs border border-rule bg-white"
        >
          {results.length === 0 && (
            <li className="px-2.5 py-2 text-[0.82rem] text-ink-2">No region matches that.</li>
          )}
          {results.map((r, i) => (
            <li key={r.code} role="option" aria-selected={r.code === value}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(r.code)}
                onMouseEnter={() => setActive(i)}
                className={
                  "flex w-full items-baseline justify-between gap-3 px-2.5 py-1.5 text-left text-[0.85rem] " +
                  (i === active ? "bg-hover" : "") +
                  (r.code === value ? " font-semibold text-pos" : " text-ink")
                }
              >
                <span className="truncate">
                  {r.name}
                  {r.official && <span className="ml-1.5 text-[0.68rem] text-pos">live feed</span>}
                  {r.operator && <span className="ml-1.5 text-[0.68rem] text-ink-2">operator</span>}
                </span>
                <span className="tnum shrink-0 text-[0.75rem] text-ink-2">
                  {r.mean.toFixed(0)} g
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
