"""Generate the region table for the dashboard from public data.

    python scripts/build_regions.py

Two free public sources, joined on ISO country codes:

* **Carbon intensity of electricity** from Our World in Data, which republishes
  Ember's Global Electricity Review. This gives each country's annual average
  gCO2eq/kWh, which is what calibrates the transferred forecast's level.
* **Country centroids** from Google's canonical countries dataset, which gives
  the latitude and longitude the weather sampling stencil is built around.

Writes ``web/src/lib/regions.generated.js``. The numbers are therefore
traceable to a source and reproducible, rather than typed in by hand.

Grid operator regions that are not whole countries (CAISO, ERCOT, PJM, NYISO)
are kept as hand-maintained entries, because no country-level dataset covers
them and their sub-national geography matters.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "src" / "lib" / "regions.generated.js"

CI_URL = ("https://ourworldindata.org/grapher/carbon-intensity-electricity.csv"
          "?v=1&csvType=full&useColumnShortNames=true")
CENTROID_URL = ("https://raw.githubusercontent.com/google/dspl/master/"
                "samples/google/canonical/countries.csv")

# Sub-national grid operators. No country dataset covers these, and their
# geography is the point, so they stay hand-maintained and clearly marked.
OPERATORS = [
    dict(code="CAISO", name="California (CAISO)", lat=36.8, lon=-119.4, mean=240),
    dict(code="ERCOT", name="Texas (ERCOT)", lat=31.0, lon=-99.0, mean=400),
    dict(code="PJM", name="US Mid-Atlantic (PJM)", lat=39.8, lon=-77.5, mean=350),
    dict(code="NYISO", name="New York (NYISO)", lat=42.9, lon=-75.5, mean=210),
    dict(code="ONT", name="Ontario", lat=44.5, lon=-79.5, mean=40),
]

# Aggregates and groupings in the OWID file that are not schedulable places.
SKIP_SUBSTRINGS = (
    "(Ember)", "(EI)", "(Shift)", "World", "OECD", "ASEAN", "EU-27", "G7", "G20",
    "income countries", "Africa", "Asia", "Europe", "America", "Oceania",
    "Middle East", "CIS", "Non-OECD", "European Union",
)


def fetch(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, timeout=120,
                     headers={"User-Agent": "gridshift/0.2 (region table build)"})
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def main() -> int:
    import pycountry

    cache = ROOT / "data"
    print("fetching carbon intensity (Our World in Data / Ember) ...")
    ci_path = fetch(CI_URL, cache / "_ci.csv")
    print("fetching country centroids (Google canonical) ...")
    ce_path = fetch(CENTROID_URL, cache / "_centroids.csv")

    # Latest year per ISO3 code.
    latest: dict[str, tuple[int, float, str]] = {}
    for row in csv.DictReader(ci_path.open(encoding="utf-8")):
        code, entity = row["code"].strip(), row["entity"].strip()
        raw = row["co2_intensity__gco2_kwh"].strip()
        if not code or not raw:
            continue
        if any(s.lower() in entity.lower() for s in SKIP_SUBSTRINGS):
            continue
        try:
            year, value = int(row["year"]), float(raw)
        except ValueError:
            continue
        if value <= 0:
            continue
        if code not in latest or year > latest[code][0]:
            latest[code] = (year, value, entity)

    print(f"  {len(latest)} countries with an intensity figure")

    # Centroids are keyed by ISO2, so map ISO3 -> ISO2.
    centroids: dict[str, tuple[float, float]] = {}
    for row in csv.DictReader(ce_path.open(encoding="utf-8")):
        try:
            centroids[row["country"].strip().upper()] = (
                float(row["latitude"]), float(row["longitude"]))
        except (ValueError, KeyError):
            continue
    print(f"  {len(centroids)} centroids")

    regions, missing = [], []
    for iso3, (year, mean, entity) in latest.items():
        try:
            rec = pycountry.countries.get(alpha_3=iso3)
            iso2 = rec.alpha_2 if rec else None
        except LookupError:
            iso2 = None
        if not iso2 or iso2 not in centroids:
            missing.append(entity)
            continue
        lat, lon = centroids[iso2]
        regions.append(dict(code=iso2, name=entity, lat=round(lat, 3),
                            lon=round(lon, 3), mean=round(mean, 1), year=year))

    regions.sort(key=lambda r: r["name"])
    print(f"  {len(regions)} joined to a centroid; {len(missing)} dropped")
    if missing:
        print("  dropped:", ", ".join(sorted(missing)[:12]),
              "..." if len(missing) > 12 else "")

    years = sorted({r["year"] for r in regions})
    print(f"  intensity years span {years[0]} to {years[-1]}")
    lo = min(regions, key=lambda r: r["mean"])
    hi = max(regions, key=lambda r: r["mean"])
    print(f"  cleanest: {lo['name']} {lo['mean']:.0f}   "
          f"dirtiest: {hi['name']} {hi['mean']:.0f} gCO2/kWh")

    body = ",\n".join(
        f'  {{ code: "{r["code"]}", name: {json.dumps(r["name"])}, '
        f'lat: {r["lat"]}, lon: {r["lon"]}, mean: {r["mean"]}, year: {r["year"]} }}'
        for r in regions
    )
    ops = ",\n".join(
        f'  {{ code: "{o["code"]}", name: {json.dumps(o["name"])}, '
        f'lat: {o["lat"]}, lon: {o["lon"]}, mean: {o["mean"]}, operator: true }}'
        for o in OPERATORS
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "/* GENERATED FILE, do not edit by hand.\n"
        " * Rebuild with: python scripts/build_regions.py\n"
        " *\n"
        " * Carbon intensity: Our World in Data, republishing Ember's Global\n"
        " * Electricity Review. Value is each country's most recent annual\n"
        " * average gCO2eq/kWh, with the year it comes from.\n"
        " * Centroids: Google canonical countries dataset.\n"
        " *\n"
        " * The intensity figure sets the level for a transferred forecast. The\n"
        " * shape still comes from the model running on that location's live\n"
        " * weather. See the limitations section of the README.\n"
        " */\n\n"
        f"export const COUNTRIES = [\n{body},\n];\n\n"
        "/* Sub-national grid operators. No country-level dataset covers these,\n"
        " * so they are hand-maintained and their figures are approximate. */\n"
        f"export const OPERATORS = [\n{ops},\n];\n",
        encoding="utf-8",
    )
    print(f"\nwrote {OUT.relative_to(ROOT)} "
          f"({len(regions)} countries + {len(OPERATORS)} operators)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
