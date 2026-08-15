"""Carbon intensity forecasting model.

A gradient-boosted tree ensemble mapping (weather forecast, calendar) ->
carbon intensity in gCO2eq/kWh.

Two things here are less standard than they look:

1. **Evaluation is decision-centric.** We report MAE/RMSE because reviewers
   expect them, but the metric we optimise for is *savings capture rate*: of
   the CO2 a perfect oracle could have saved by moving a job, how much does
   this forecast actually capture? A forecast with a large constant bias can
   score terribly on MAE and perfectly on capture rate, because scheduling
   only cares about the *ordering* of hours.

2. **The model exports to JSON** and runs in the browser. The published
   dashboard has no backend at all -- the same trees that were fit here are
   evaluated in ~40 lines of JavaScript on the client.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from .features import build_features


@dataclass
class Metrics:
    mae: float
    rmse: float
    r2: float
    n: int

    def line(self, label: str) -> str:
        return (f"{label:<34s} MAE {self.mae:7.2f}   RMSE {self.rmse:7.2f}   "
                f"R2 {self.r2:6.3f}")


def evaluate(y_true: np.ndarray, y_pred: np.ndarray) -> Metrics:
    return Metrics(
        mae=float(mean_absolute_error(y_true, y_pred)),
        rmse=float(np.sqrt(mean_squared_error(y_true, y_pred))),
        r2=float(r2_score(y_true, y_pred)),
        n=int(len(y_true)),
    )


# --------------------------------------------------------------------------
# baselines
# --------------------------------------------------------------------------
class HourOfDayClimatology:
    """Predict the training-set mean intensity for this (hour, is_weekend).

    This is the baseline that matters. Anyone can tell you "the grid is
    cleaner at 3am" -- if a machine-learning model cannot beat that, it has
    earned nothing. Beating it means the model is genuinely reading the
    *weather*, not just the clock.
    """

    def __init__(self) -> None:
        self.table: dict[tuple[int, int], float] = {}
        self.fallback: float = 0.0

    def fit(self, ts: pd.Series, y: np.ndarray) -> HourOfDayClimatology:
        df = pd.DataFrame({
            "hour": ts.dt.hour,
            "wknd": (ts.dt.dayofweek >= 5).astype(int),
            "y": y,
        })
        self.table = df.groupby(["hour", "wknd"])["y"].mean().to_dict()
        self.fallback = float(np.mean(y))
        return self

    def predict(self, ts: pd.Series) -> np.ndarray:
        hours = ts.dt.hour.to_numpy()
        wknd = (ts.dt.dayofweek >= 5).astype(int).to_numpy()
        return np.array([
            self.table.get((int(h), int(w)), self.fallback)
            for h, w in zip(hours, wknd)
        ])


class SeasonalClimatology:
    """Mean intensity for this (month, hour) -- a stronger, fairer baseline."""

    def __init__(self) -> None:
        self.table: dict[tuple[int, int], float] = {}
        self.fallback: float = 0.0

    def fit(self, ts: pd.Series, y: np.ndarray) -> SeasonalClimatology:
        df = pd.DataFrame({"m": ts.dt.month, "h": ts.dt.hour, "y": y})
        self.table = df.groupby(["m", "h"])["y"].mean().to_dict()
        self.fallback = float(np.mean(y))
        return self

    def predict(self, ts: pd.Series) -> np.ndarray:
        return np.array([
            self.table.get((int(m), int(h)), self.fallback)
            for m, h in zip(ts.dt.month, ts.dt.hour)
        ])


# --------------------------------------------------------------------------
# main model
# --------------------------------------------------------------------------
DEFAULT_PARAMS: dict[str, Any] = {
    "max_iter": 400,
    "learning_rate": 0.06,
    "max_depth": 7,
    "min_samples_leaf": 25,
    "l2_regularization": 1.0,
    "early_stopping": True,
    "validation_fraction": 0.12,
    "n_iter_no_change": 30,
    "random_state": 42,
}


class CarbonIntensityModel:
    """Weather + calendar -> gCO2eq/kWh."""

    def __init__(self, **params: Any) -> None:
        self.params = {**DEFAULT_PARAMS, **params}
        self.reg = HistGradientBoostingRegressor(**self.params)
        self.feature_names_: list[str] = []
        self.trained_on_: dict[str, Any] = {}

    # -- fit / predict ---------------------------------------------------
    def fit(self, raw: pd.DataFrame, y: np.ndarray) -> CarbonIntensityModel:
        X = build_features(raw)
        self.feature_names_ = list(X.columns)
        self.reg.fit(X.to_numpy(), y)
        ts = pd.to_datetime(raw["ts"], utc=True)
        self.trained_on_ = {
            "rows": int(len(X)),
            "start": ts.min().isoformat(),
            "end": ts.max().isoformat(),
        }
        return self

    def predict(self, raw: pd.DataFrame) -> np.ndarray:
        X = build_features(raw)
        X = X[self.feature_names_]          # guarantee column order
        # Intensity is physically non-negative; clip rather than let the
        # ensemble extrapolate into nonsense on unusual weather.
        return np.clip(self.reg.predict(X.to_numpy()), 0.0, None)

    def permutation_importance(self, raw: pd.DataFrame, y: np.ndarray,
                               *, n_repeats: int = 3,
                               seed: int = 0) -> pd.DataFrame:
        """Which features actually carry the signal (MAE degradation when shuffled)."""
        rng = np.random.default_rng(seed)
        X = build_features(raw)[self.feature_names_].to_numpy()
        base = mean_absolute_error(y, np.clip(self.reg.predict(X), 0, None))
        rows = []
        for j, name in enumerate(self.feature_names_):
            deltas = []
            for _ in range(n_repeats):
                Xp = X.copy()
                rng.shuffle(Xp[:, j])
                deltas.append(
                    mean_absolute_error(y, np.clip(self.reg.predict(Xp), 0, None)) - base)
            rows.append({"feature": name, "mae_increase": float(np.mean(deltas))})
        return (pd.DataFrame(rows)
                .sort_values("mae_increase", ascending=False)
                .reset_index(drop=True))

    # -- persistence -----------------------------------------------------
    def save(self, path: str | Path) -> None:
        import joblib
        joblib.dump(self, Path(path))

    @staticmethod
    def load(path: str | Path) -> CarbonIntensityModel:
        import joblib
        return joblib.load(Path(path))

    # -- browser export --------------------------------------------------
    def to_json(self) -> dict[str, Any]:
        """Serialise the fitted ensemble so JavaScript can evaluate it.

        ``HistGradientBoostingRegressor`` stores each boosting stage as a
        ``TreePredictor`` whose ``nodes`` is a flat structured array. We keep
        only the five fields needed at inference time and emit them as
        parallel arrays, which keeps the payload small and the JS evaluator
        trivial (see ``web/model.js``).
        """
        trees = []
        for stage in self.reg._predictors:
            for pred in stage:                       # one per output; we have 1
                nodes = pred.nodes
                trees.append({
                    "f": nodes["feature_idx"].astype(int).tolist(),
                    "t": [round(float(v), 6) for v in nodes["num_threshold"]],
                    "l": nodes["left"].astype(int).tolist(),
                    "r": nodes["right"].astype(int).tolist(),
                    "v": [round(float(v), 6) for v in nodes["value"]],
                    "leaf": nodes["is_leaf"].astype(int).tolist(),
                    "m": nodes["missing_go_to_left"].astype(int).tolist(),
                })
        baseline = float(np.ravel(self.reg._baseline_prediction)[0])
        return {
            "format": "gridshift-hgbr-v1",
            "baseline": baseline,
            "features": self.feature_names_,
            "n_trees": len(trees),
            "trees": trees,
            "trained_on": self.trained_on_,
            "exported_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        }

    def export_json(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_json(), separators=(",", ":")), encoding="utf-8")
        return p

    def predict_from_json_spec(self, X: np.ndarray) -> np.ndarray:
        """Reference implementation of the JSON evaluator, used by tests.

        Mirrors ``web/model.js`` exactly so that a test can assert the browser
        and Python paths agree.
        """
        spec = self.to_json()
        out = np.full(len(X), spec["baseline"], dtype=float)
        for tree in spec["trees"]:
            feat, thr, left, right, val, is_leaf, miss_left = (
                tree["f"], tree["t"], tree["l"], tree["r"],
                tree["v"], tree["leaf"], tree["m"])
            for i, row in enumerate(X):
                node = 0
                while not is_leaf[node]:
                    x = row[feat[node]]
                    if np.isnan(x):
                        node = left[node] if miss_left[node] else right[node]
                    else:
                        node = left[node] if x <= thr[node] else right[node]
                out[i] += val[node]
        return np.clip(out, 0.0, None)
