"""Data access for GridShift.

Two free, key-less sources:

* **UK National Grid Carbon Intensity API** (``api.carbonintensity.org.uk``) --
  half-hourly carbon intensity (gCO2eq/kWh) and generation mix for Great
  Britain, plus a 48h-ahead official forecast. This is our *ground truth*: one
  of the very few grids on Earth that publishes open, real-time, forecast
  carbon intensity with no API key.

* **Open-Meteo** (``open-meteo.com``) -- global weather, both a historical
  reanalysis archive and a 16-day forecast. Free, key-less, worldwide.

The pairing is the whole point of the project. We learn *weather -> carbon
intensity* where ground truth exists, then apply it where it does not.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import requests

CI_BASE = "https://api.carbonintensity.org.uk"
OM_FORECAST = "https://api.open-meteo.com/v1/forecast"
OM_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

USER_AGENT = "GridShift/0.1 (+https://github.com/gridshift) research prototype"

# Weather variables that physically drive a grid's carbon intensity:
#   wind_speed_100m     -> wind turbine hub-height output
#   shortwave_radiation -> solar PV output
#   temperature_2m      -> heating/cooling demand
#   cloud_cover         -> solar, and a proxy for weather regime
HOURLY_VARS = [
    "temperature_2m",
    "wind_speed_100m",
    "shortwave_radiation",
    "cloud_cover",
]

# Sites chosen to span the GB generation fleet rather than the population:
# Scottish + North Sea wind dominates marginal supply, the South East drives
# demand, and Wales/Midlands sit in between. Averaging four sites gives the
# model a crude but effective picture of a weather *system* crossing the
# country instead of a single point.
GB_SITES: list[tuple[str, float, float]] = [
    ("scotland", 57.15, -2.10),   # Aberdeenshire - onshore + North Sea wind
    ("north_england", 54.05, -1.50),  # Yorkshire
    ("wales", 52.40, -3.90),      # mid Wales - wind
    ("south_east", 51.30, 0.30),  # London/Kent - demand + solar
]


class DataError(RuntimeError):
    """Raised when an upstream API cannot be reached or returns junk."""


# --------------------------------------------------------------------------
# small HTTP helper
# --------------------------------------------------------------------------
def _get_json(url: str, *, params: dict | None = None, retries: int = 4,
              timeout: int = 45) -> dict[str, Any]:
    """GET with linear backoff. Upstream APIs are free and occasionally flaky."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(
                url, params=params, timeout=timeout,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - we genuinely want any failure
            last = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise DataError(f"GET {url} failed after {retries} attempts: {last}")


def _iso_z(t: dt.datetime) -> str:
    """UK CI API wants minute-resolution Zulu timestamps: 2026-08-14T23:30Z."""
    return t.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%MZ")


def _chunks(start: dt.datetime, end: dt.datetime,
            days: int) -> Iterator[tuple[dt.datetime, dt.datetime]]:
    """Yield [start, end) sub-ranges. The CI API caps a request at 14 days."""
    cur = start
    step = dt.timedelta(days=days)
    while cur < end:
        nxt = min(cur + step, end)
        yield cur, nxt
        cur = nxt


# --------------------------------------------------------------------------
# UK Carbon Intensity API
# --------------------------------------------------------------------------
def fetch_intensity_now() -> dict[str, Any]:
    """Current half-hour settlement period for GB."""
    payload = _get_json(f"{CI_BASE}/intensity")
    rows = payload.get("data") or []
    if not rows:
        raise DataError("carbonintensity.org.uk returned no current data")
    return rows[0]


def fetch_intensity_forecast_48h(
    start: dt.datetime | None = None,
) -> pd.DataFrame:
    """Official National Grid ESO 48h-ahead carbon intensity forecast.

    This is the incumbent we benchmark against -- and the thing that only
    exists for a handful of grids worldwide.
    """
    start = start or dt.datetime.now(dt.UTC)
    payload = _get_json(f"{CI_BASE}/intensity/{_iso_z(start)}/fw48h")
    return _intensity_rows_to_frame(payload.get("data") or [])


def fetch_intensity_range(start: dt.datetime, end: dt.datetime,
                          *, chunk_days: int = 13,
                          progress: bool = True) -> pd.DataFrame:
    """Historical half-hourly carbon intensity between two datetimes."""
    frames: list[pd.DataFrame] = []
    windows = list(_chunks(start, end, chunk_days))
    for i, (a, b) in enumerate(windows, 1):
        payload = _get_json(f"{CI_BASE}/intensity/{_iso_z(a)}/{_iso_z(b)}")
        frames.append(_intensity_rows_to_frame(payload.get("data") or []))
        if progress:
            print(f"  intensity chunk {i}/{len(windows)}  "
                  f"{a:%Y-%m-%d} -> {b:%Y-%m-%d}", flush=True)
        time.sleep(0.3)  # be a good citizen on a free public API
    if not frames:
        raise DataError("no intensity data returned")
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)


def _intensity_rows_to_frame(rows: Iterable[dict]) -> pd.DataFrame:
    recs = []
    for r in rows:
        inten = r.get("intensity") or {}
        recs.append({
            "ts": pd.Timestamp(r["from"]).tz_convert("UTC"),
            "actual": inten.get("actual"),
            "forecast_official": inten.get("forecast"),
            "index": inten.get("index"),
        })
    df = pd.DataFrame(recs)
    if df.empty:
        return pd.DataFrame(columns=["ts", "actual", "forecast_official", "index"])
    for col in ("actual", "forecast_official"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def fetch_generation_range(start: dt.datetime, end: dt.datetime,
                           *, chunk_days: int = 13,
                           progress: bool = True) -> pd.DataFrame:
    """Historical half-hourly GB generation mix (percentage by fuel).

    Not used as a model *input* (it would leak -- you cannot know tomorrow's
    fuel mix), but invaluable for the analysis in the README and for sanity
    checking that the model has learned real physics.
    """
    frames: list[pd.DataFrame] = []
    windows = list(_chunks(start, end, chunk_days))
    for i, (a, b) in enumerate(windows, 1):
        payload = _get_json(f"{CI_BASE}/generation/{_iso_z(a)}/{_iso_z(b)}")
        recs = []
        for row in payload.get("data") or []:
            rec: dict[str, Any] = {"ts": pd.Timestamp(row["from"]).tz_convert("UTC")}
            for fuel in row.get("generationmix") or []:
                rec[f"mix_{fuel['fuel']}"] = fuel["perc"]
            recs.append(rec)
        frames.append(pd.DataFrame(recs))
        if progress:
            print(f"  generation chunk {i}/{len(windows)}  "
                  f"{a:%Y-%m-%d} -> {b:%Y-%m-%d}", flush=True)
        time.sleep(0.3)
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)


# --------------------------------------------------------------------------
# Open-Meteo
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Site:
    name: str
    lat: float
    lon: float


@dataclass
class WeatherBundle:
    """Weather for a set of sites, already aligned on a common hourly index."""
    frame: pd.DataFrame
    sites: list[Site] = field(default_factory=list)


def _openmeteo_to_frame(payload: dict, prefix: str) -> pd.DataFrame:
    hourly = payload.get("hourly") or {}
    if "time" not in hourly:
        raise DataError(f"open-meteo returned no hourly block for {prefix}")
    df = pd.DataFrame({"ts": pd.to_datetime(hourly["time"], utc=True)})
    for var in HOURLY_VARS:
        if var in hourly:
            df[f"{prefix}_{var}"] = pd.to_numeric(
                pd.Series(hourly[var]), errors="coerce")
    return df


def fetch_weather_archive(sites: list[tuple[str, float, float]],
                          start: dt.date, end: dt.date,
                          *, progress: bool = True) -> pd.DataFrame:
    """Historical hourly reanalysis weather for each site, joined on time."""
    merged: pd.DataFrame | None = None
    for name, lat, lon in sites:
        payload = _get_json(OM_ARCHIVE, params={
            "latitude": lat, "longitude": lon,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "hourly": ",".join(HOURLY_VARS),
            "timezone": "UTC",
        })
        df = _openmeteo_to_frame(payload, name)
        merged = df if merged is None else merged.merge(df, on="ts", how="outer")
        if progress:
            print(f"  weather archive: {name} ({len(df)} hours)", flush=True)
        time.sleep(0.5)
    assert merged is not None
    return merged.sort_values("ts").reset_index(drop=True)


def fetch_weather_forecast(sites: list[tuple[str, float, float]],
                           *, days: int = 3) -> pd.DataFrame:
    """Hourly weather forecast for each site, joined on time."""
    merged: pd.DataFrame | None = None
    for name, lat, lon in sites:
        payload = _get_json(OM_FORECAST, params={
            "latitude": lat, "longitude": lon,
            "hourly": ",".join(HOURLY_VARS),
            "forecast_days": days,
            "timezone": "UTC",
        })
        df = _openmeteo_to_frame(payload, name)
        merged = df if merged is None else merged.merge(df, on="ts", how="outer")
        time.sleep(0.3)
    assert merged is not None
    return merged.sort_values("ts").reset_index(drop=True)


def sites_around(lat: float, lon: float, *, spread_deg: float = 2.0
                 ) -> list[tuple[str, float, float]]:
    """Build a 4-point sampling stencil around an arbitrary location.

    For zero-shot transfer to a grid we have no training data for, we cannot
    know where its wind farms are. Sampling a cross centred on the requested
    point at roughly the spatial scale of a synoptic weather system is a
    deliberately crude stand-in -- see the calibration caveats in the README.
    """
    return [
        ("scotland", lat + spread_deg, lon),          # slot 0: "windy north"
        ("north_england", lat, lon - spread_deg),
        ("wales", lat, lon + spread_deg),
        ("south_east", lat - spread_deg, lon),        # slot 3: "demand centre"
    ]
