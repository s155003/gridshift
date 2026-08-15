"""Tests for feature engineering and the natural-language fallback parser."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gridshift.agent import _fallback_parse  # noqa: E402
from gridshift.data import HOURLY_VARS, sites_around  # noqa: E402
from gridshift.features import CUT_IN, CUT_OUT, RATED, build_features, turbine_curve  # noqa: E402


# --------------------------------------------------------------------------
# turbine physics
# --------------------------------------------------------------------------
def test_turbine_curve_boundaries():
    assert turbine_curve(np.array([0.0]))[0] == 0.0
    assert turbine_curve(np.array([CUT_IN - 0.01]))[0] == 0.0
    assert turbine_curve(np.array([RATED]))[0] == pytest.approx(1.0)
    assert turbine_curve(np.array([20.0]))[0] == pytest.approx(1.0)
    # Turbines feather in a storm: output collapses above cut-out.
    assert turbine_curve(np.array([CUT_OUT]))[0] == 0.0
    assert turbine_curve(np.array([40.0]))[0] == 0.0


def test_turbine_curve_is_monotonic_in_the_ramp():
    w = np.linspace(CUT_IN, RATED, 60)
    p = turbine_curve(w)
    assert np.all(np.diff(p) >= -1e-12)
    assert np.all((p >= 0) & (p <= 1))


def test_turbine_curve_is_cubic_not_linear():
    """Halving wind speed should cut output far more than half."""
    mid = (CUT_IN + RATED) / 2
    assert turbine_curve(np.array([mid]))[0] < 0.5


# --------------------------------------------------------------------------
# feature matrix
# --------------------------------------------------------------------------
def make_frame(n=48, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-03-01", periods=n, freq="1h", tz="UTC")
    df = pd.DataFrame({"ts": ts})
    for name in ("scotland", "north_england", "wales", "south_east"):
        df[f"{name}_temperature_2m"] = rng.uniform(-2, 28, n)
        df[f"{name}_wind_speed_100m"] = rng.uniform(0, 90, n)   # km/h
        df[f"{name}_shortwave_radiation"] = rng.uniform(0, 900, n)
        df[f"{name}_cloud_cover"] = rng.uniform(0, 100, n)
    return df


def test_features_are_finite_and_shaped():
    X = build_features(make_frame())
    assert len(X) == 48
    assert X.shape[1] == 31
    assert np.isfinite(X.to_numpy()).all()


def test_cyclical_encoding_wraps():
    """23:00 and 00:00 must be neighbours, not opposite extremes."""
    ts = pd.to_datetime(["2026-03-01T23:00Z", "2026-03-02T00:00Z"], utc=True)
    df = make_frame(2)
    df["ts"] = ts
    X = build_features(df)
    d = np.hypot(X.hour_sin.iloc[1] - X.hour_sin.iloc[0],
                 X.hour_cos.iloc[1] - X.hour_cos.iloc[0])
    assert d < 0.3


def test_degree_days_are_one_sided():
    df = make_frame(4)
    for c in df.columns:
        if c.endswith("temperature_2m"):
            df[c] = [0.0, 10.0, 20.0, 30.0]
    X = build_features(df)
    assert X.heating_degrees.iloc[0] > 0 and X.cooling_degrees.iloc[0] == 0
    assert X.cooling_degrees.iloc[3] > 0 and X.heating_degrees.iloc[3] == 0


def test_dunkelflaute_peaks_when_calm_and_dark():
    df = make_frame(2)
    for c in df.columns:
        if c.endswith("wind_speed_100m"):
            df[c] = [0.0, 80.0]
        if c.endswith("shortwave_radiation"):
            df[c] = [0.0, 900.0]
    X = build_features(df)
    assert X.dunkelflaute.iloc[0] > X.dunkelflaute.iloc[1]
    assert X.renew_proxy.iloc[1] > X.renew_proxy.iloc[0]


def test_km_per_hour_is_converted_to_metres_per_second():
    """Open-Meteo reports km/h; the physics needs m/s."""
    df = make_frame(1)
    for c in df.columns:
        if c.endswith("wind_speed_100m"):
            df[c] = [36.0]                     # 36 km/h == 10 m/s
    X = build_features(df)
    assert X.wind_speed_mean.iloc[0] == pytest.approx(10.0)


def test_sites_around_produces_four_named_slots():
    sites = sites_around(40.0, -100.0)
    assert len(sites) == 4
    assert [s[0] for s in sites] == ["scotland", "north_england", "wales", "south_east"]
    assert all(len(HOURLY_VARS) == 4 for _ in sites)


# --------------------------------------------------------------------------
# fallback NL parser (the no-API-key path)
# --------------------------------------------------------------------------
NOW = dt.datetime(2026, 3, 1, 14, 0, tzinfo=dt.UTC)


def test_fallback_reads_explicit_duration_and_power():
    p = _fallback_parse("run for 3 hours at 2.5 kW", now=NOW)
    assert p.spec.duration_hours == pytest.approx(3.0)
    assert p.spec.power_kw == pytest.approx(2.5)


def test_fallback_converts_watts():
    p = _fallback_parse("train for 4 hours on a 700W GPU", now=NOW)
    assert p.spec.power_kw == pytest.approx(0.7)


def test_fallback_infers_ev_charging_is_splittable():
    p = _fallback_parse("charge my EV for 6 hours overnight", now=NOW)
    assert p.spec.interruptible is True
    assert p.spec.power_kw == pytest.approx(7.0)
    assert p.spec.name == "EV charge"


def test_fallback_keeps_dishwasher_atomic():
    p = _fallback_parse("run the dishwasher for 2 hours before 7am", now=NOW)
    assert p.spec.interruptible is False


def test_fallback_parses_clock_deadline():
    p = _fallback_parse("finish by 8am", now=NOW)
    assert p.spec.deadline is not None
    hours = (p.spec.deadline - NOW).total_seconds() / 3600
    assert hours == pytest.approx(18.0)   # 14:00 today -> 08:00 tomorrow


def test_fallback_never_exceeds_the_horizon():
    p = _fallback_parse("sometime this week", now=NOW, horizon_hours=48)
    assert (p.spec.deadline - NOW).total_seconds() / 3600 <= 48
