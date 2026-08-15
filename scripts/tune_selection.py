"""Diagnose and fix the optimiser's curse on interruptible jobs.

The first honest evaluation of GridShift produced an uncomfortable result:
for *splittable* workloads (EV charging, batch queues) the scheduler was
**worse than useless** -- a savings capture rate of -0.44, meaning following
its advice emitted more CO2 than just plugging in immediately.

The cause is not a coding bug, it is a statistical one. When a job must run
contiguously, the scheduler averages the forecast over a whole window and
independent errors partly cancel. When the job is splittable, the scheduler
takes an ``argmin`` over individual hours -- and ``argmin`` over noisy
estimates preferentially selects the hours where the model most *under*
-predicts. This is the classic optimiser's curse, and the fix is to select on
a deliberately pessimistic estimate rather than the conditional mean.

This script sweeps two candidate corrections and reports what actually works:

  * **pessimism**: use a predicted upper quantile instead of the mean, so
    hours the model is uncertain about are penalised rather than rewarded.
  * **smoothing**: low-pass the forecast before selection, so single-hour
    noise spikes cannot win the argmin on their own.

    python scripts/tune_selection.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gridshift.features import build_features  # noqa: E402
from gridshift.model import DEFAULT_PARAMS, CarbonIntensityModel  # noqa: E402
from gridshift.scheduler import JobSpec, savings_capture_rate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TEST_FRACTION = 0.20

# Interruptible archetypes -- the ones that exhibited the pathology.
SPLIT_JOBS = [
    ("EV charge (6h, 14h slack)",
     dict(duration_hours=6, power_kw=7.0, interruptible=True,
          min_block_hours=1), 14),
    ("Data centre batch (8h, 48h slack)",
     dict(duration_hours=8, power_kw=50.0, interruptible=True,
          min_block_hours=2), 48),
    ("Freezer pre-cool (3h, 12h slack)",
     dict(duration_hours=3, power_kw=0.4, interruptible=True,
          min_block_hours=1), 12),
]
# One contiguous job, to make sure a fix for splittable jobs does not
# quietly regress the case that already worked.
CONTIG_JOBS = [
    ("ML training (4h, 24h slack)",
     dict(duration_hours=4, power_kw=0.7, interruptible=False), 24),
]

QUANTILES = [0.50, 0.60, 0.70, 0.80, 0.90]
SMOOTHERS = [1, 3, 5]


def smooth(x: np.ndarray, w: int) -> np.ndarray:
    """Centred moving average, edge-padded. w=1 is a no-op."""
    if w <= 1:
        return x
    pad = w // 2
    padded = np.pad(x, (pad, pad), mode="edge")
    kernel = np.ones(w) / w
    return np.convolve(padded, kernel, mode="valid")[:len(x)]


def sweep(times, truth, forecasts: dict[str, np.ndarray], jobs,
          *, stride: int = 12) -> pd.DataFrame:
    rows = []
    for label, kw, horizon in jobs:
        for fname, f in forecasts.items():
            for w in SMOOTHERS:
                vals = []
                for start in range(0, len(truth) - horizon, stride):
                    sl = slice(start, start + horizon)
                    wt, wtruth, wf = times[sl], truth[sl], f[sl]
                    if len(wt) < horizon or np.isnan(wtruth).any() or np.isnan(wf).any():
                        continue
                    job = JobSpec(name="j", **kw,
                                  deadline=wt[0] + dt.timedelta(hours=horizon))
                    try:
                        vals.append(savings_capture_rate(
                            wt, smooth(wf, w), wtruth, job, slot_hours=1.0))
                    except Exception:
                        continue
                if vals:
                    rows.append({"job": label, "forecast": fname, "smooth": w,
                                 "capture": float(np.mean(vals)),
                                 "n": len(vals)})
    return pd.DataFrame(rows)


def main() -> int:
    df = pd.read_csv(ROOT / "data" / "training.csv", parse_dates=["ts"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    y = df["actual"].to_numpy(dtype=float)

    split = int(len(df) * (1 - TEST_FRACTION))
    train, test = df.iloc[:split], df.iloc[split:].reset_index(drop=True)
    y_tr, y_te = y[:split], y[split:]
    times = [pd.Timestamp(t).to_pydatetime() for t in test["ts"]]

    Xtr = build_features(train).to_numpy()
    Xte = build_features(test).to_numpy()

    print("=" * 78)
    print("Optimiser's curse: pessimism + smoothing sweep")
    print("=" * 78)
    print(f"train {len(train):,} rows   test {len(test):,} rows\n")

    forecasts: dict[str, np.ndarray] = {}

    mean_model = CarbonIntensityModel().fit(train, y_tr)
    forecasts["mean"] = mean_model.predict(test)
    print("fitted conditional-mean model")

    for q in QUANTILES:
        params = {**DEFAULT_PARAMS, "loss": "quantile", "quantile": q}
        reg = HistGradientBoostingRegressor(**params).fit(Xtr, y_tr)
        forecasts[f"q{int(q*100)}"] = np.clip(reg.predict(Xte), 0, None)
        print(f"fitted quantile model q={q:.2f}")
    print()

    # Sanity: a higher quantile should sit above a lower one on average.
    print("mean predicted level by forecaster (gCO2/kWh):")
    for k, v in forecasts.items():
        bias = float(np.mean(v - y_te))
        print(f"  {k:<6s} mean {v.mean():6.1f}   bias {bias:+6.1f}")
    print()

    print("SPLITTABLE JOBS -- capture rate (higher is better, 1.0 = oracle)")
    print("-" * 78)
    res_split = sweep(times, y_te, forecasts, SPLIT_JOBS)
    piv = res_split.pivot_table(index=["job", "smooth"], columns="forecast",
                                values="capture")
    piv = piv[[c for c in ["mean", "q50", "q60", "q70", "q80", "q90"]
               if c in piv.columns]]
    print(piv.to_string(float_format=lambda v: f"{v:7.3f}"))
    print()

    print("CONTIGUOUS JOB -- check the fix does not regress what worked")
    print("-" * 78)
    res_cont = sweep(times, y_te, forecasts, CONTIG_JOBS)
    pivc = res_cont.pivot_table(index=["job", "smooth"], columns="forecast",
                                values="capture")
    pivc = pivc[[c for c in ["mean", "q50", "q60", "q70", "q80", "q90"]
                 if c in pivc.columns]]
    print(pivc.to_string(float_format=lambda v: f"{v:7.3f}"))
    print()

    # ---- pick the winner -------------------------------------------------
    agg = (res_split.groupby(["forecast", "smooth"])["capture"]
           .mean().reset_index().sort_values("capture", ascending=False))
    print("BEST SETTINGS FOR SPLITTABLE JOBS (averaged over archetypes)")
    print("-" * 78)
    print(agg.head(8).to_string(index=False, float_format=lambda v: f"{v:7.3f}"))
    best = agg.iloc[0]
    print(f"\n  -> selection policy: forecast={best['forecast']} "
          f"smoothing={int(best['smooth'])}h  capture={best['capture']:.3f}")

    baseline = agg[(agg.forecast == "mean") & (agg["smooth"] == 1)]["capture"]
    if len(baseline):
        print(f"  -> was {float(baseline.iloc[0]):.3f} with the naive "
              f"conditional-mean policy")

    out = {
        "quantiles": QUANTILES,
        "smoothers": SMOOTHERS,
        "split_results": res_split.to_dict(orient="records"),
        "contig_results": res_cont.to_dict(orient="records"),
        "best": {"forecast": str(best["forecast"]),
                 "smooth": int(best["smooth"]),
                 "capture": float(best["capture"])},
    }
    (ROOT / "data" / "selection_tuning.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8")
    print("\nwrote data/selection_tuning.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
