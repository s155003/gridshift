"""Why is today's saving small? Show the grid spread and how it interacts with slack.

    python scripts/explain_today.py

GridShift's savings are not a fixed property of the tool -- they are a property
of the grid on the day. This prints the live spread alongside what each job
archetype can capture right now, which is the honest answer to "why is the
number lower than the README's averages?"
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gridshift.forecast import forecast_region  # noqa: E402
from gridshift.scheduler import JobSpec, optimize  # noqa: E402

ARCHETYPES = [
    # name, hours, kW, splittable, deadline hours
    ("EV charge", 6, 7.0, True, 11),
    ("Dishwasher", 2, 1.2, False, 12),
    ("ML training run", 4, 0.7, False, 24),
    ("Data-centre batch", 8, 50.0, True, 48),
]


def main(region: str = "GB") -> int:
    fc = forecast_region(region, hours=48)
    lo, hi = float(fc.intensity.min()), float(fc.intensity.max())

    print(f"\n{fc.region.name}, next {len(fc)}h ({fc.tier} forecast)")
    print(f"  range  {lo:.0f}–{hi:.0f} gCO2/kWh")
    print(f"  spread {hi - lo:.0f} g   ratio {hi / max(lo, 1):.1f}x")
    print("  (README figures average 107 rolling windows across a full year,")
    print("   where the range was 20-282 gCO2/kWh, a 13.8x ratio)")
    print()
    print(f"  {'job':<22}{'slack':>7}{'saved':>8}   {'window chosen':<22}")
    print("  " + "-" * 60)

    for name, hours, kw, split, deadline_h in ARCHETYPES:
        job = JobSpec(
            name=name, duration_hours=hours, power_kw=kw, interruptible=split,
            min_block_hours=2 if split else 1,
            deadline=fc.times[0] + dt.timedelta(hours=deadline_h),
            earliest_start=fc.times[0],
        )
        try:
            r = optimize(fc.times, fc.intensity, job, slot_hours=fc.slot_hours)
        except Exception as exc:
            print(f"  {name:<22}{deadline_h:>5}h   n/a    ({exc})")
            continue
        when = ", ".join(f"{b.start:%a %H:%M}-{b.end:%H:%M}" for b in r.blocks)
        print(f"  {name:<22}{deadline_h:>5}h{r.saved_pct:>7.0f}%   {when:<22}")

    print()
    print("  Savings scale with (a) how much the grid moves today and (b) how much")
    print("  deadline slack the job has. A tight deadline on a flat day genuinely")
    print("  has little to capture, and GridShift reports that rather than inflating it.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "GB"))
