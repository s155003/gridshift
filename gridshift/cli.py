"""GridShift command line interface.

    gridshift schedule "train my model for 4 hours, done before 8am"
    gridshift forecast --region CAISO
    gridshift now
    gridshift regions
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

import numpy as np

from . import __version__
from .agent import explain, parse_job
from .forecast import REGIONS, current_intensity_gb, forecast_region
from .scheduler import ScheduleError, optimize

BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values, lo=None, hi=None) -> str:
    v = np.asarray(values, dtype=float)
    lo = float(v.min()) if lo is None else lo
    hi = float(v.max()) if hi is None else hi
    if hi - lo < 1e-9:
        return BLOCKS[0] * len(v)
    idx = np.clip(((v - lo) / (hi - lo) * (len(BLOCKS) - 1)).round().astype(int),
                  0, len(BLOCKS) - 1)
    return "".join(BLOCKS[i] for i in idx)


def chart(times, values, marked: set[int]) -> str:
    """Sparkline with the chosen slots marked, and an hour ruler beneath."""
    line = sparkline(values)
    marks = "".join("▲" if i in marked else " " for i in range(len(values)))
    lo, hi = float(np.min(values)), float(np.max(values))
    head = f"  {lo:.0f}–{hi:.0f} gCO₂/kWh over the next {len(values)}h"

    # Hour labels every 6 slots, each written into the two cells starting at
    # its tick so the digits sit under the point they describe.
    ruler = [" "] * len(times)
    for i, t in enumerate(times):
        if t.hour % 6 == 0 and i + 1 < len(times):
            label = f"{t.hour:02d}"
            ruler[i], ruler[i + 1] = label[0], label[1]
    return f"{head}\n  {line}\n  {marks}\n  {''.join(ruler)}"


def cmd_now(args) -> int:
    row = current_intensity_gb()
    inten = row.get("intensity", {})
    val = inten.get("actual") or inten.get("forecast")
    print(f"Great Britain, {row['from']}")
    print(f"  {val} gCO2/kWh  ({inten.get('index')})")
    return 0


def cmd_regions(args) -> int:
    print(f"{'CODE':<8}{'REGION':<26}{'ANNUAL MEAN':>12}   SOURCE")
    print("-" * 72)
    for r in REGIONS.values():
        src = "operator API + model" if r.has_official_api else "transferred model"
        print(f"{r.code:<8}{r.name:<26}{r.annual_mean_gco2:>9.0f} g   {src}")
    print("\nOnly GB has a public carbon-intensity API. Every other region is a")
    print("level-calibrated transfer of the GB-trained model -- see README.")
    return 0


def cmd_forecast(args) -> int:
    fc = forecast_region(args.region, hours=args.hours)
    print(fc.describe())
    if fc.note:
        print(f"  note: {fc.note}")
    print()
    print(chart(fc.times, fc.intensity, set()))
    if args.json:
        print()
        print(json.dumps(
            [{"ts": t.isoformat(), "gco2_per_kwh": round(float(v), 1)}
             for t, v in zip(fc.times, fc.intensity)], indent=2))
    return 0


def cmd_schedule(args) -> int:
    fc = forecast_region(args.region, hours=args.hours)
    parsed = parse_job(" ".join(args.request), horizon_hours=len(fc))

    if args.duration:
        parsed.spec.duration_hours = args.duration
    if args.power:
        parsed.spec.power_kw = args.power
    if args.deadline:
        parsed.spec.deadline = fc.times[0] + dt.timedelta(hours=args.deadline)

    try:
        result = optimize(fc.times, fc.intensity, parsed.spec,
                          slot_hours=fc.slot_hours)
    except ScheduleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "region": fc.region.code,
            "forecast_tier": fc.tier,
            "job": {
                "name": parsed.spec.name,
                "duration_hours": parsed.spec.duration_hours,
                "power_kw": parsed.spec.power_kw,
                "interruptible": parsed.spec.interruptible,
                "deadline": parsed.spec.deadline.isoformat()
                if parsed.spec.deadline else None,
            },
            "parsed_by": parsed.source,
            "parser_notes": parsed.reasoning,
            "blocks": [{"start": b.start.isoformat(), "end": b.end.isoformat()}
                       for b in result.blocks],
            "energy_kwh": round(result.energy_kwh, 3),
            "optimal_gco2": round(result.optimal_g, 1),
            "naive_gco2": round(result.naive_g, 1),
            "saved_gco2": round(result.saved_g, 1),
            "saved_pct": round(result.saved_pct, 1),
            "car_km_equivalent": round(result.car_km_equivalent, 1),
        }, indent=2))
        return 0

    marked = {i for b in result.blocks for i in range(b.start_index, b.end_index)}

    print(f"\n  GridShift  ·  {fc.region.name}  ·  {fc.tier} forecast")
    print("  " + "─" * 60)
    print(f"  job     : {parsed.spec.name}")
    print(f"  needs   : {parsed.spec.duration_hours:g}h at "
          f"{parsed.spec.power_kw:g} kW = {result.energy_kwh:.1f} kWh"
          f"{'  (splittable)' if parsed.spec.interruptible else ''}")
    if parsed.spec.deadline:
        print(f"  deadline: {parsed.spec.deadline:%a %d %b %H:%M} UTC")
    print(f"  parsed  : {parsed.source}"
          + (f" — {parsed.reasoning}" if parsed.reasoning else ""))
    print()
    print(chart(fc.times, fc.intensity, marked))
    print()
    for b in result.blocks:
        print(f"  ▶ run {b.start:%a %d %b %H:%M} → {b.end:%H:%M}")
    print()
    print(f"  now      {result.naive_intensity:>6.0f} gCO2/kWh   "
          f"{result.naive_g/1000:>7.2f} kg")
    print(f"  shifted  {result.optimal_intensity:>6.0f} gCO2/kWh   "
          f"{result.optimal_g/1000:>7.2f} kg")
    print(f"  saved    {result.saved_pct:>6.0f} %           "
          f"{result.saved_g/1000:>7.2f} kg   "
          f"(≈{result.car_km_equivalent:.0f} km not driven)")
    print()
    print("  " + explain(result, fc, parsed=parsed).replace("\n", "\n  "))
    print()
    if fc.tier == "transferred":
        print("  ⚠ this region has no public carbon API; the forecast is a")
        print("    calibrated transfer of the GB-trained model. Treat the shape")
        print("    as indicative and the level as approximate.\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="gridshift",
        description="Move flexible electricity demand to the cleanest hours.")
    p.add_argument("--version", action="version", version=f"gridshift {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("schedule", help="find the lowest-carbon window for a job")
    s.add_argument("request", nargs="+", help="plain-language description of the job")
    s.add_argument("--region", default="GB")
    s.add_argument("--hours", type=int, default=48)
    s.add_argument("--duration", type=float, help="override duration (hours)")
    s.add_argument("--power", type=float, help="override power draw (kW)")
    s.add_argument("--deadline", type=float, help="override deadline (hours from now)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_schedule)

    f = sub.add_parser("forecast", help="show the carbon intensity forecast")
    f.add_argument("--region", default="GB")
    f.add_argument("--hours", type=int, default=48)
    f.add_argument("--json", action="store_true")
    f.set_defaults(func=cmd_forecast)

    n = sub.add_parser("now", help="current GB carbon intensity")
    n.set_defaults(func=cmd_now)

    r = sub.add_parser("regions", help="list supported regions")
    r.set_defaults(func=cmd_regions)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
