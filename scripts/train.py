"""Train and honestly evaluate the GridShift forecaster.

    python scripts/train.py

Protocol
--------
The data are split chronologically into train (70%) / validation (15%) /
test (15%). Nothing is ever fit or chosen on the test set:

  * model parameters are fit on **train**
  * the scheduling policy (loss function + smoothing width) is selected on
    **validation**
  * every number reported as a result comes from **test**, touched once

Produces:
    models/carbon_model.joblib   the fitted production model
    web/model.json               the same trees, for in-browser inference
    data/metrics.json            every number quoted in the README
    assets/*.png                 evaluation charts
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gridshift.model import (  # noqa: E402
    CarbonIntensityModel,
    HourOfDayClimatology,
    SeasonalClimatology,
    evaluate,
)
from gridshift.scheduler import JobSpec, optimize, savings_capture_rate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TRAIN_FRAC, VAL_FRAC = 0.70, 0.15

# Realistic flexible loads spanning the two dimensions that matter: job
# length, and how much slack it has before its deadline.
JOB_ARCHETYPES = [
    ("ML training run (4h, GPU, by tomorrow)",
     dict(duration_hours=4, power_kw=0.7, interruptible=False), 24),
    ("EV charge (6h, splittable, overnight)",
     dict(duration_hours=6, power_kw=7.0, interruptible=True,
          min_block_hours=1), 14),
    ("CI batch (2h, within the workday)",
     dict(duration_hours=2, power_kw=0.3, interruptible=False), 8),
    ("Dishwasher (2h, by morning)",
     dict(duration_hours=2, power_kw=1.2, interruptible=False), 12),
    ("Data centre batch (8h, splittable, 48h slack)",
     dict(duration_hours=8, power_kw=50.0, interruptible=True,
          min_block_hours=2), 48),
]

SMOOTH_GRID = [0, 3, 5, 7]


def _times(frame: pd.DataFrame) -> list[dt.datetime]:
    return [pd.Timestamp(t).to_pydatetime() for t in frame["ts"]]


def mean_capture(times, truth, forecast, *, smooth_hours, stride=12,
                 jobs=JOB_ARCHETYPES) -> dict[str, float]:
    """Mean savings capture rate per archetype for one forecast + policy."""
    out: dict[str, float] = {}
    for label, kw, horizon in jobs:
        vals = []
        for start in range(0, len(truth) - horizon, stride):
            sl = slice(start, start + horizon)
            wt, wtruth, wf = times[sl], truth[sl], forecast[sl]
            if len(wt) < horizon or np.isnan(wtruth).any() or np.isnan(wf).any():
                continue
            job = JobSpec(name="j", **kw,
                          deadline=wt[0] + dt.timedelta(hours=horizon))
            try:
                vals.append(savings_capture_rate(
                    wt, wf, wtruth, job, slot_hours=1.0,
                    smooth_hours=smooth_hours))
            except Exception:
                continue
        out[label] = float(np.mean(vals)) if vals else float("nan")
    return out


def realised_savings(times, truth, forecast, *, smooth_hours, stride=12) -> dict:
    """Actual gCO2 reduction achieved by following the model's advice."""
    out = {}
    for label, kw, horizon in JOB_ARCHETYPES:
        naive_t, opt_t = [], []
        for start in range(0, len(truth) - horizon, stride):
            sl = slice(start, start + horizon)
            wt, wtruth, wf = times[sl], truth[sl], forecast[sl]
            if len(wt) < horizon or np.isnan(wtruth).any() or np.isnan(wf).any():
                continue
            job = JobSpec(name="j", **kw,
                          deadline=wt[0] + dt.timedelta(hours=horizon))
            try:
                plan = optimize(wt, wf, job, slot_hours=1.0,
                                smooth_hours=smooth_hours)
            except Exception:
                continue
            eps = job.power_kw
            got = sum(float(wtruth[b.start_index:b.end_index].sum()) * eps
                      for b in plan.blocks)
            n = int(np.ceil(job.duration_hours))
            naive_t.append(float(wtruth[:n].sum()) * eps)
            opt_t.append(got)
        if naive_t:
            tn, to = float(np.sum(naive_t)), float(np.sum(opt_t))
            out[label] = {
                "naive_g": tn, "scheduled_g": to,
                "reduction_pct": 100.0 * (tn - to) / tn if tn else 0.0,
                "windows": len(naive_t),
            }
    return out


def main() -> int:
    csv = ROOT / "data" / "training.csv"
    if not csv.exists():
        print("No dataset. Run: python scripts/build_dataset.py", file=sys.stderr)
        return 1

    df = pd.read_csv(csv, parse_dates=["ts"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    y = df["actual"].to_numpy(dtype=float)

    i1 = int(len(df) * TRAIN_FRAC)
    i2 = int(len(df) * (TRAIN_FRAC + VAL_FRAC))
    train = df.iloc[:i1]
    val = df.iloc[i1:i2].reset_index(drop=True)
    test = df.iloc[i2:].reset_index(drop=True)
    y_tr, y_va, y_te = y[:i1], y[i1:i2], y[i2:]

    print("=" * 78)
    print("GridShift  |  carbon intensity forecasting from weather alone")
    print("=" * 78)
    print(f"rows   : {len(df):,}  ({df.ts.min():%Y-%m-%d} -> {df.ts.max():%Y-%m-%d})")
    print(f"split  : train {len(train):,} | val {len(val):,} | test {len(test):,}"
          "   (chronological, no shuffling)")
    print(f"target : {y.min():.0f} .. {y.max():.0f} gCO2/kWh, mean {y.mean():.0f}"
          f"   ({y.max()/max(y.min(),1):.1f}x spread)")
    print()

    # ---- fit both candidate losses on TRAIN only ------------------------
    print("fitting models on train ...")
    m_mean = CarbonIntensityModel().fit(train, y_tr)
    m_med = CarbonIntensityModel(loss="quantile", quantile=0.5).fit(train, y_tr)
    print(f"  squared-error model : {m_mean.reg.n_iter_} iterations")
    print(f"  median (L1) model   : {m_med.reg.n_iter_} iterations")
    print(f"  {len(m_mean.feature_names_)} features\n")

    candidates = {"squared-error": m_mean, "median-L1": m_med}

    # ---- choose the scheduling policy on VALIDATION ---------------------
    print("POLICY SELECTION  (validation set only -- test is untouched here)")
    print("-" * 78)
    t_va = _times(val)
    rows = []
    for cname, cmodel in candidates.items():
        p_va = cmodel.predict(val)
        for w in SMOOTH_GRID:
            caps = mean_capture(t_va, y_va, p_va, smooth_hours=w)
            rows.append({"loss": cname, "smooth_h": w,
                         "mean_capture": float(np.nanmean(list(caps.values())))})
    sel = pd.DataFrame(rows).sort_values("mean_capture", ascending=False)
    print(sel.to_string(index=False, float_format=lambda v: f"{v:7.3f}"))
    best = sel.iloc[0]
    best_loss, best_smooth = str(best["loss"]), int(best["smooth_h"])
    naive_row = sel[(sel.loss == "squared-error") & (sel.smooth_h == 0)]
    print(f"\n  chosen: loss={best_loss}, smoothing={best_smooth}h  "
          f"(val capture {best['mean_capture']:.3f})")
    if len(naive_row):
        print(f"  vs. the unsmoothed squared-error policy: "
              f"{float(naive_row.iloc[0]['mean_capture']):.3f}")
    print()

    model = candidates[best_loss]

    # ---- everything below is the single pass over TEST -------------------
    pred = model.predict(test)
    hod = HourOfDayClimatology().fit(train["ts"], y_tr)
    sea = SeasonalClimatology().fit(train["ts"], y_tr)

    preds = {
        "persistence (train mean)": np.full(len(test), y_tr.mean()),
        "hour-of-day climatology": hod.predict(test["ts"]),
        "month x hour climatology": sea.predict(test["ts"]),
        "GridShift (weather ML)": pred,
    }
    # The official National Grid ESO forecast is the incumbent. It sees
    # generator dispatch schedules and interconnector plans that no public
    # weather API exposes -- not a fair fight, which is why it is the ceiling
    # worth measuring against rather than a competitor.
    official = test["forecast_official"].to_numpy(dtype=float)
    has_official = np.isfinite(official).mean() > 0.8
    if has_official:
        preds["National Grid official forecast"] = official

    print("ACCURACY  (test set, never seen during fitting or policy choice)")
    print("-" * 78)
    metrics = {}
    for name, p in preds.items():
        ok = np.isfinite(p)
        m = evaluate(y_te[ok], p[ok])
        metrics[name] = {"mae": m.mae, "rmse": m.rmse, "r2": m.r2, "n": m.n}
        print("  " + m.line(name))

    ml_mae = metrics["GridShift (weather ML)"]["mae"]
    hod_mae = metrics["hour-of-day climatology"]["mae"]
    print(f"\n  -> {100*(1-ml_mae/hod_mae):.1f}% lower MAE than the "
          f"hour-of-day baseline")
    if has_official:
        off_mae = metrics["National Grid official forecast"]["mae"]
        print(f"  -> {ml_mae/off_mae:.2f}x the error of the grid operator's own "
              f"forecast, using only public weather")
    print()

    # ---- the metric that actually matters -------------------------------
    print(f"SAVINGS CAPTURE RATE  (test set, policy = {best_loss} "
          f"+ {best_smooth}h smoothing)")
    print("-" * 78)
    t_te = _times(test)
    cap_rows = []
    for name, p in preds.items():
        if not np.isfinite(p).all():
            continue
        caps = mean_capture(t_te, y_te, p, smooth_hours=best_smooth)
        cap_rows.append({"forecast": name, **caps})
    cap = pd.DataFrame(cap_rows).set_index("forecast").T
    print(cap.to_string(float_format=lambda v: f"{v:7.3f}"))

    # Show what the naive policy would have done, to justify the fix.
    naive_caps = mean_capture(t_te, y_te, pred, smooth_hours=0)
    print("\n  GridShift WITHOUT the smoothing fix (test):")
    for k, v in naive_caps.items():
        fixed = cap.loc[k, "GridShift (weather ML)"]
        print(f"    {k:<46s} {v:6.3f}  ->  {fixed:6.3f}")
    print()

    # ---- what it means in kgCO2 -----------------------------------------
    print("REALISED EMISSIONS REDUCTION  (measured against real grid data)")
    print("-" * 78)
    rs = realised_savings(t_te, y_te, pred, smooth_hours=best_smooth)
    for label, v in rs.items():
        print(f"  {label:<46s} -{v['reduction_pct']:5.1f}%  "
              f"({v['windows']} windows)")
    print()

    print("TOP FEATURES  (permutation importance, MAE increase when shuffled)")
    print("-" * 78)
    imp = model.permutation_importance(test, y_te, n_repeats=3)
    for _, r in imp.head(10).iterrows():
        print(f"  {r['feature']:<24s} +{r['mae_increase']:6.2f} gCO2/kWh")
    print()

    # ---- persist ---------------------------------------------------------
    (ROOT / "models").mkdir(exist_ok=True)
    model.save(ROOT / "models" / "carbon_model.joblib")
    spec = model.to_json()
    spec["smooth_hours"] = best_smooth
    (ROOT / "web" / "model.json").write_text(
        json.dumps(spec, separators=(",", ":")), encoding="utf-8")
    size = (ROOT / "web" / "model.json").stat().st_size / 1024
    print("saved model      -> models/carbon_model.joblib")
    print(f"exported for web -> web/model.json ({size:.0f} KB, "
          f"{spec['n_trees']} trees)")

    payload = {
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "dataset": {
            "rows": int(len(df)),
            "start": df.ts.min().isoformat(), "end": df.ts.max().isoformat(),
            "train_rows": int(len(train)), "val_rows": int(len(val)),
            "test_rows": int(len(test)),
            "intensity_min": float(y.min()), "intensity_max": float(y.max()),
            "intensity_mean": float(y.mean()),
        },
        "policy": {"loss": best_loss, "smooth_hours": best_smooth,
                   "val_capture": float(best["mean_capture"]),
                   "selection_table": sel.to_dict(orient="records")},
        "accuracy": metrics,
        "capture_rate": cap.to_dict(),
        "capture_rate_without_fix": naive_caps,
        "realised_savings": rs,
        "feature_importance": imp.head(15).to_dict(orient="records"),
        "n_features": len(model.feature_names_),
        "n_trees": spec["n_trees"],
    }
    (ROOT / "data" / "metrics.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")
    print("wrote metrics    -> data/metrics.json")

    try:
        make_charts(test, y_te, preds, cap, rs, naive_caps)
        print("wrote charts     -> assets/")
    except Exception as exc:
        print(f"(charts skipped: {exc})")
    return 0


def make_charts(test, y_te, preds, cap, rs, naive_caps) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    ink, accent, muted, warn = "#0f172a", "#059669", "#94a3b8", "#f59e0b"

    # 1. a representative fortnight, prediction vs truth
    fig, ax = plt.subplots(figsize=(12, 4.2), dpi=150)
    n = min(336, len(test))
    t = test["ts"].iloc[:n]
    ax.fill_between(t, 0, y_te[:n], color=muted, alpha=.25)
    ax.plot(t, y_te[:n], color=ink, lw=1.3, label="actual")
    ax.plot(t, preds["GridShift (weather ML)"][:n], color=accent, lw=1.6,
            label="GridShift (weather only)")
    ax.plot(t, preds["hour-of-day climatology"][:n], color=warn, lw=1.1,
            ls="--", label="hour-of-day baseline")
    ax.set_ylabel("gCO$_2$eq / kWh")
    ax.set_title("GB carbon intensity forecast from weather alone, held-out test period",
                 loc="left", fontsize=12, color=ink)
    ax.legend(frameon=False, ncol=3, fontsize=9)
    ax.grid(alpha=.2)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(assets / "forecast.png")
    plt.close(fig)

    # 2. capture rate by job archetype
    fig, ax = plt.subplots(figsize=(11, 4.6), dpi=150)
    jobs = list(cap.index)
    labels = [j.split(" (")[0] for j in jobs]
    srcs = [s for s in ["hour-of-day climatology", "GridShift (weather ML)",
                        "National Grid official forecast"] if s in cap.columns]
    colors = {"hour-of-day climatology": warn,
              "GridShift (weather ML)": accent,
              "National Grid official forecast": "#6366f1"}
    width = 0.8 / len(srcs)
    x = np.arange(len(labels))
    for i, s in enumerate(srcs):
        ax.bar(x + i * width, [cap.loc[j, s] for j in jobs], width,
               label=s, color=colors[s])
    ax.set_xticks(x + width * (len(srcs) - 1) / 2)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("savings capture rate")
    ax.axhline(1.0, color=ink, lw=.8, ls=":")
    ax.axhline(0.0, color=ink, lw=.8)
    ax.set_title("Fraction of achievable CO$_2$ saving captured (1.0 = perfect foresight)",
                 loc="left", fontsize=12, color=ink)
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="y", alpha=.2)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(assets / "capture_rate.png")
    plt.close(fig)

    # 3. the optimiser's-curse fix
    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=150)
    jobs2 = list(naive_caps.keys())
    labels2 = [j.split(" (")[0] for j in jobs2]
    before = [naive_caps[j] for j in jobs2]
    after = [cap.loc[j, "GridShift (weather ML)"] for j in jobs2]
    x = np.arange(len(labels2))
    ax.bar(x - 0.2, before, 0.4, label="argmin on raw forecast", color="#ef4444")
    ax.bar(x + 0.2, after, 0.4, label="with pre-selection smoothing", color=accent)
    ax.set_xticks(x)
    ax.set_xticklabels(labels2, fontsize=8.5)
    ax.axhline(0, color=ink, lw=.8)
    ax.set_ylabel("savings capture rate")
    ax.set_title("Countering the optimiser's curse (test set)",
                 loc="left", fontsize=12, color=ink)
    ax.legend(frameon=False, fontsize=9)
    ax.grid(axis="y", alpha=.2)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(assets / "optimizer_curse.png")
    plt.close(fig)

    # 4. realised reduction per job type
    fig, ax = plt.subplots(figsize=(9, 3.8), dpi=150)
    names = [k.split(" (")[0] for k in rs]
    vals = [v["reduction_pct"] for v in rs.values()]
    bars = ax.barh(names, vals, color=accent)
    for b, v in zip(bars, vals):
        ax.text(b.get_width() + .4, b.get_y() + b.get_height() / 2,
                f"−{v:.0f}%", va="center", fontsize=10, color=ink)
    ax.set_xlabel("CO$_2$ reduction vs. running immediately (%)")
    ax.set_title("Real emissions cut, measured against actual grid data",
                 loc="left", fontsize=12, color=ink)
    ax.grid(axis="x", alpha=.2)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(assets / "savings.png")
    plt.close(fig)


if __name__ == "__main__":
    raise SystemExit(main())
