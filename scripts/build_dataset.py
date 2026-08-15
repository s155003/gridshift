"""Download and assemble the GridShift training set.

Pulls ~12 months of real GB carbon intensity + generation mix and pairs it
with real reanalysis weather from four sites spanning the GB generation
fleet. Everything comes from free, key-less public APIs.

    python scripts/build_dataset.py --months 12

Writes ``data/training.parquet`` (and a CSV copy for easy inspection).
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gridshift import data as D  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=12)
    # The Open-Meteo reanalysis archive lags real time by roughly five days.
    ap.add_argument("--lag-days", type=int, default=7,
                    help="stop this many days before today (archive lag)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    end = (dt.datetime.now(dt.UTC) - dt.timedelta(days=args.lag_days)
           ).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - dt.timedelta(days=30 * args.months)

    print("GridShift dataset build")
    print(f"  window : {start:%Y-%m-%d} -> {end:%Y-%m-%d} "
          f"({(end - start).days} days)")
    print()

    print("[1/3] carbon intensity (National Grid ESO)")
    intensity = D.fetch_intensity_range(start, end)
    print(f"  -> {len(intensity):,} half-hourly rows\n")

    print("[2/3] generation mix (National Grid ESO)")
    try:
        generation = D.fetch_generation_range(start, end)
        print(f"  -> {len(generation):,} half-hourly rows\n")
    except D.DataError as exc:
        print(f"  !! generation mix unavailable ({exc}); continuing without\n")
        generation = pd.DataFrame(columns=["ts"])

    print("[3/3] weather reanalysis (Open-Meteo archive)")
    weather = D.fetch_weather_archive(
        D.GB_SITES, start.date(), end.date())
    print(f"  -> {len(weather):,} hourly rows\n")

    # --- align to a common hourly grid -----------------------------------
    # Carbon intensity is native half-hourly (GB settlement periods); weather
    # is hourly. We downsample intensity rather than upsampling weather so
    # that every training row is backed by a real observation.
    intensity = intensity.set_index("ts")
    hourly_int = intensity[["actual", "forecast_official"]].resample("1h").mean()
    hourly_int = hourly_int.reset_index()

    df = hourly_int.merge(weather, on="ts", how="inner")

    if not generation.empty:
        gen = generation.set_index("ts").resample("1h").mean().reset_index()
        df = df.merge(gen, on="ts", how="left")

    before = len(df)
    df = df.dropna(subset=["actual"]).reset_index(drop=True)
    print(f"aligned: {before:,} rows -> {len(df):,} with a real intensity value")

    wcols = [c for c in df.columns if any(v in c for v in D.HOURLY_VARS)]
    df[wcols] = df[wcols].interpolate(limit=3).ffill(limit=3).bfill(limit=3)
    df = df.dropna(subset=wcols).reset_index(drop=True)

    print(f"final  : {len(df):,} rows x {len(df.columns)} columns")
    print(f"  intensity  min={df.actual.min():.0f}  "
          f"mean={df.actual.mean():.0f}  max={df.actual.max():.0f} gCO2/kWh")
    print(f"  ratio max/min within dataset: {df.actual.max()/max(df.actual.min(),1):.1f}x")

    pq = OUT_DIR / "training.parquet"
    try:
        df.to_parquet(pq, index=False)
        print(f"\nwrote {pq}")
    except Exception as exc:  # pyarrow may be absent
        print(f"\nparquet unavailable ({exc})")
    csv = OUT_DIR / "training.csv"
    df.to_csv(csv, index=False)
    print(f"wrote {csv}  ({csv.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
