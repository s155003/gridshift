"""Live forecasting: turn a place and a moment into a carbon intensity curve.

Three tiers, in descending order of trustworthiness:

``official``
    The grid operator publishes its own forecast. Today that is Great Britain
    (National Grid ESO). Use it -- it sees generator dispatch schedules we
    never will.

``modelled``
    We run our trained model on a live weather forecast. Validated against GB
    ground truth. This is what GridShift is for.

``transferred``
    The same model, pointed at a grid it was never trained on, with an affine
    calibration to that grid's published annual average. The *shape* (when the
    clean hours are) transfers because it is driven by weather and demand
    rhythms; the *level* is calibrated. Clearly labelled, because the
    uncertainty is real and unquantified -- see the README.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from . import data as D
from .model import CarbonIntensityModel

Tier = Literal["official", "modelled", "transferred"]

MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "carbon_model.joblib"


@dataclass(frozen=True)
class Region:
    """A grid region GridShift can forecast for.

    ``annual_mean_gco2`` is the published annual average carbon intensity used
    to calibrate the transferred forecast's level. Figures are approximate
    operational averages for recent years, drawn from Ember's Global
    Electricity Review and the respective system operators. They are
    deliberately overridable -- a user who knows their grid better than we do
    should say so.
    """
    code: str
    name: str
    lat: float
    lon: float
    annual_mean_gco2: float
    has_official_api: bool = False


REGIONS: dict[str, Region] = {r.code: r for r in [
    Region("GB", "Great Britain", 54.0, -2.0, 124, has_official_api=True),
    Region("FR", "France", 46.8, 2.4, 56),
    Region("DE", "Germany", 51.2, 10.4, 381),
    Region("ES", "Spain", 40.4, -3.7, 150),
    Region("PL", "Poland", 52.2, 19.1, 662),
    Region("SE", "Sweden", 62.0, 15.0, 30),
    Region("IE", "Ireland", 53.3, -7.7, 320),
    Region("CAISO", "California (CAISO)", 36.8, -119.4, 240),
    Region("ERCOT", "Texas (ERCOT)", 31.0, -99.0, 400),
    Region("PJM", "US Mid-Atlantic (PJM)", 39.8, -77.5, 350),
    Region("NYISO", "New York (NYISO)", 42.9, -75.5, 210),
    Region("ONT", "Ontario", 44.5, -79.5, 40),
    Region("IN", "India", 21.0, 79.0, 713),
    Region("AU", "Australia (NEM)", -33.0, 147.0, 550),
    Region("JP", "Japan", 36.2, 138.3, 490),
    Region("BR", "Brazil", -14.0, -51.0, 120),
]}


@dataclass
class Forecast:
    region: Region
    tier: Tier
    times: list[dt.datetime]
    intensity: np.ndarray
    issued: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.UTC))
    note: str = ""

    def __len__(self) -> int:
        return len(self.times)

    @property
    def slot_hours(self) -> float:
        if len(self.times) < 2:
            return 1.0
        return (self.times[1] - self.times[0]).total_seconds() / 3600.0

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame({"ts": self.times, "intensity": self.intensity})

    def describe(self) -> str:
        lo, hi = float(self.intensity.min()), float(self.intensity.max())
        tiers = {
            "official": "grid operator's own forecast",
            "modelled": "GridShift model on live weather (validated)",
            "transferred": "GridShift model transferred + level-calibrated "
                           "(EXPERIMENTAL, see README)",
        }
        return (f"{self.region.name}: {len(self)} slots, "
                f"{lo:.0f}-{hi:.0f} gCO2/kWh  [{tiers[self.tier]}]")


_MODEL_CACHE: CarbonIntensityModel | None = None


def load_model(path: Path | str = MODEL_PATH) -> CarbonIntensityModel:
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"No trained model at {p}. Run: python scripts/train.py")
        _MODEL_CACHE = CarbonIntensityModel.load(p)
    return _MODEL_CACHE


def forecast_region(code: str = "GB", *, hours: int = 48,
                    prefer_official: bool = True,
                    model: CarbonIntensityModel | None = None) -> Forecast:
    """Best available carbon intensity forecast for a region."""
    region = REGIONS.get(code.upper())
    if region is None:
        raise KeyError(f"unknown region {code!r}. "
                       f"Known: {', '.join(sorted(REGIONS))}")

    if region.has_official_api and prefer_official:
        try:
            df = D.fetch_intensity_forecast_48h()
            df = df.dropna(subset=["forecast_official"]).head(hours * 2)
            if len(df) >= 4:
                # Official feed is half-hourly; resample to hourly slots.
                s = (df.set_index("ts")["forecast_official"]
                     .resample("1h").mean().dropna().head(hours))
                return Forecast(
                    region=region, tier="official",
                    times=[pd.Timestamp(t).to_pydatetime() for t in s.index],
                    intensity=s.to_numpy(dtype=float),
                    note="National Grid ESO published forecast")
        except Exception as exc:  # fall through to the model
            note = f"official feed unavailable ({type(exc).__name__}); using model"
        else:
            note = ""
    else:
        note = ""

    return forecast_from_weather(region, hours=hours, model=model, note=note)


def forecast_from_weather(region: Region, *, hours: int = 48,
                          model: CarbonIntensityModel | None = None,
                          note: str = "") -> Forecast:
    """Run the trained model on a live weather forecast for ``region``."""
    model = model or load_model()

    sites = (D.GB_SITES if region.code == "GB"
             else D.sites_around(region.lat, region.lon))
    days = max(2, min(7, hours // 24 + 1))
    wx = D.fetch_weather_forecast(sites, days=days)

    now = dt.datetime.now(dt.UTC).replace(minute=0, second=0, microsecond=0)
    wx = wx[wx["ts"] >= now].head(hours).reset_index(drop=True)
    if wx.empty:
        raise D.DataError("no future weather rows returned")

    raw = model.predict(wx)

    if region.code == "GB":
        tier: Tier = "modelled"
        inten = raw
    else:
        # Affine level calibration. The model was fit on GB, so its outputs
        # live on GB's scale; rescaling by the ratio of annual averages keeps
        # the diurnal/weather *shape* while putting the magnitude in the right
        # place for this grid. This is a documented approximation, not a
        # validated transfer -- we have no ground truth here to check it.
        gb_mean = REGIONS["GB"].annual_mean_gco2
        scale = region.annual_mean_gco2 / gb_mean
        inten = raw * scale
        tier = "transferred"
        note = (note + " " if note else "") + (
            f"level-calibrated x{scale:.2f} to {region.name}'s published "
            f"annual mean ({region.annual_mean_gco2:.0f} gCO2/kWh)")

    return Forecast(
        region=region, tier=tier,
        times=[pd.Timestamp(t).to_pydatetime() for t in wx["ts"]],
        intensity=np.clip(inten, 0.0, None),
        note=note.strip())


def current_intensity_gb() -> dict:
    """Live GB carbon intensity, for the 'right now' readout."""
    return D.fetch_intensity_now()
