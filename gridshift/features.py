"""Feature engineering: weather + clock -> features a grid model can use.

Design constraint that shapes everything here: **no autoregressive inputs.**

It would be easy (and much more accurate) to feed the model the last few hours
of measured carbon intensity. We deliberately do not, because the entire point
of GridShift is to forecast for grids that publish *no* intensity data at all.
A model that needs yesterday's intensity to predict tomorrow's cannot be
transferred. So every feature below is derivable from (a) a public weather
forecast and (b) a calendar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .data import GB_SITES

SITE_NAMES = [s[0] for s in GB_SITES]

# --- wind turbine power curve -------------------------------------------
# Wind power is not linear in wind speed, so handing a tree model raw m/s
# wastes its capacity on relearning basic physics. These are representative
# values for a modern utility-scale turbine (m/s at 100m hub height).
CUT_IN = 3.5
RATED = 12.5
CUT_OUT = 25.0

# Degree-day bases for GB. Below ~15.5C people heat; above ~22C they cool.
HEAT_BASE_C = 15.5
COOL_BASE_C = 22.0


def turbine_curve(wind_ms: np.ndarray) -> np.ndarray:
    """Normalised turbine output in [0, 1] for hub-height wind speed in m/s.

    Cubic ramp from cut-in to rated, flat at rated power until cut-out, then
    zero (turbines feather in a storm -- which is why very high wind can
    coincide with *falling* wind generation).
    """
    w = np.asarray(wind_ms, dtype=float)
    out = np.zeros_like(w)

    ramp = (w >= CUT_IN) & (w < RATED)
    out[ramp] = (w[ramp] ** 3 - CUT_IN ** 3) / (RATED ** 3 - CUT_IN ** 3)

    out[(w >= RATED) & (w < CUT_OUT)] = 1.0
    # >= CUT_OUT stays 0.0
    return np.clip(out, 0.0, 1.0)


def _kmh_to_ms(x: pd.Series) -> pd.Series:
    """Open-Meteo reports wind in km/h by default; the physics wants m/s."""
    return x / 3.6


def build_features(df: pd.DataFrame, *, site_names: list[str] | None = None
                   ) -> pd.DataFrame:
    """Turn a raw joined weather frame into the model's feature matrix.

    ``df`` must contain a UTC ``ts`` column and, for each site,
    ``{site}_temperature_2m``, ``{site}_wind_speed_100m``,
    ``{site}_shortwave_radiation``, ``{site}_cloud_cover``.

    The site *names* are positional slots, not geography -- see
    :func:`gridshift.data.sites_around`. Slot 0 is the "windy" corner and
    slot 3 the "demand centre" corner, which is what lets the same trained
    model be pointed at a grid it has never seen.
    """
    names = site_names or SITE_NAMES
    ts = pd.to_datetime(df["ts"], utc=True)
    f = pd.DataFrame(index=df.index)

    # ---- calendar ------------------------------------------------------
    hour = ts.dt.hour + ts.dt.minute / 60.0
    dow = ts.dt.dayofweek
    doy = ts.dt.dayofyear

    # Cyclical encodings so that 23:00 and 00:00 are neighbours, not extremes.
    f["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    f["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    f["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    f["dow_cos"] = np.cos(2 * np.pi * dow / 7)
    f["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    f["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    f["is_weekend"] = (dow >= 5).astype(float)
    # Weekday working hours: the demand ramp that drives gas onto the margin.
    f["is_workhours"] = ((dow < 5) & (hour >= 7) & (hour < 19)).astype(float)

    # ---- per-site weather ----------------------------------------------
    winds_ms, solars, temps, clouds = [], [], [], []
    for i, name in enumerate(names):
        w_ms = _kmh_to_ms(df[f"{name}_wind_speed_100m"].astype(float))
        power = turbine_curve(w_ms.to_numpy())

        f[f"wind_power_{i}"] = power
        f[f"solar_{i}"] = df[f"{name}_shortwave_radiation"].astype(float) / 1000.0

        winds_ms.append(w_ms.to_numpy())
        solars.append(df[f"{name}_shortwave_radiation"].astype(float).to_numpy())
        temps.append(df[f"{name}_temperature_2m"].astype(float).to_numpy())
        clouds.append(df[f"{name}_cloud_cover"].astype(float).to_numpy())

    W = np.vstack(winds_ms)          # (n_sites, n_rows)
    P = turbine_curve(W)
    S = np.vstack(solars)
    T = np.vstack(temps)
    C = np.vstack(clouds)

    # ---- fleet-level aggregates ----------------------------------------
    # Mean turbine output across sites is the single best proxy we have for
    # "how much of the grid is being served by wind right now".
    f["wind_power_mean"] = P.mean(axis=0)
    f["wind_power_min"] = P.min(axis=0)
    f["wind_power_max"] = P.max(axis=0)
    # Spread matters: a becalmed *whole country* is the classic high-carbon
    # event ("Dunkelflaute"). Low mean AND low spread is much worse than low
    # mean with one region still blowing.
    f["wind_power_spread"] = P.max(axis=0) - P.min(axis=0)
    f["wind_speed_mean"] = W.mean(axis=0)

    f["solar_mean"] = S.mean(axis=0) / 1000.0
    f["solar_max"] = S.max(axis=0) / 1000.0
    f["cloud_mean"] = C.mean(axis=0) / 100.0

    temp_mean = T.mean(axis=0)
    f["temp_mean"] = temp_mean
    f["temp_spread"] = T.max(axis=0) - T.min(axis=0)
    # Demand responds asymmetrically to temperature, so split the two limbs
    # rather than hoping the model finds the kink.
    f["heating_degrees"] = np.clip(HEAT_BASE_C - temp_mean, 0, None)
    f["cooling_degrees"] = np.clip(temp_mean - COOL_BASE_C, 0, None)

    # ---- interactions ---------------------------------------------------
    # Renewable supply vs. the daily demand shape. When wind is low *and* it
    # is a cold weekday evening, the marginal plant is almost certainly gas.
    f["dunkelflaute"] = (1.0 - f["wind_power_mean"]) * (1.0 - f["solar_mean"].clip(0, 1))
    f["renew_proxy"] = f["wind_power_mean"] + 0.5 * f["solar_mean"].clip(0, 1)
    f["stress"] = f["dunkelflaute"] * (1.0 + f["heating_degrees"] / 10.0)

    return f.astype(float)


FEATURE_ORDER: list[str] | None = None


def feature_names(df_features: pd.DataFrame) -> list[str]:
    return list(df_features.columns)
