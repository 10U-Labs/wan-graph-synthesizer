#!/usr/bin/env python3
"""Build the municipality reference CSV from public Census flat files.

Run once to (re)generate ``data/reference/municipalities.csv``; the committed CSV
is the artifact the designer reads at runtime (this script never runs in CI).
County names come from the county totals file purely to label each place's
county (the county-to-metro crosswalk lives in ``build_metro_reference.py``).
Three public Census sources are joined:

* county totals -- ``co-est2023-alldata.csv`` (SUMLEV 050)
* place totals + place->county parts -- ``sub-est2023.csv`` (SUMLEV 162 and 157)
* place internal-point coordinates -- the 2023 national places Gazetteer

A place that straddles counties is assigned the county holding the largest share
of its population (the largest SUMLEV 157 part). Census files are Latin-1.
"""

from __future__ import annotations

import csv
import io
import urllib.request
import zipfile
from pathlib import Path

COUNTY_URL = (
    "https://www2.census.gov/programs-surveys/popest/datasets/"
    "2020-2023/counties/totals/co-est2023-alldata.csv"
)
SUBEST_URL = (
    "https://www2.census.gov/programs-surveys/popest/datasets/"
    "2020-2023/cities/totals/sub-est2023.csv"
)
GAZ_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2023_Gazetteer/2023_Gaz_place_national.zip"
)

REFERENCE_DIR = Path("data/reference")
POP_FIELD = "POPESTIMATE2023"

FIPS_TO_USPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY",
}


def _fetch(url: str) -> bytes:
    """Download a Census file's raw bytes."""
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 (static Census URLs)
        return bytes(response.read())


def _rows(raw: bytes) -> list[dict[str, str]]:
    """Parse Latin-1 CSV bytes into dict rows."""
    return list(csv.DictReader(io.StringIO(raw.decode("latin-1"))))


def county_names(raw: bytes) -> dict[tuple[str, str], str]:
    """A ``(state_fips, county_fips) -> CTYNAME`` index for labeling places (SUMLEV 050)."""
    name_by_fips: dict[tuple[str, str], str] = {}
    for row in _rows(raw):
        if row["SUMLEV"] != "050" or FIPS_TO_USPS.get(row["STATE"]) is None:
            continue
        name_by_fips[(row["STATE"], row["COUNTY"])] = row["CTYNAME"]
    return name_by_fips


def _primary_county(subest: list[dict[str, str]]) -> dict[tuple[str, str], str]:
    """For each ``(state, place)``, the county FIPS holding its largest population part."""
    best: dict[tuple[str, str], tuple[int, str]] = {}
    for row in subest:
        if row["SUMLEV"] != "157":
            continue
        key = (row["STATE"], row["PLACE"])
        part = int(row[POP_FIELD])
        if key not in best or part > best[key][0]:
            best[key] = (part, row["COUNTY"])
    return {key: county for key, (_part, county) in best.items()}


def _place_coords(raw: bytes) -> dict[tuple[str, str], tuple[str, str]]:
    """Map ``(state_fips, place_fips)`` to ``(latitude, longitude)`` from the Gazetteer."""
    coords: dict[tuple[str, str], tuple[str, str]] = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        text = archive.read(archive.namelist()[0]).decode("latin-1")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    reader.fieldnames = [name.strip() for name in reader.fieldnames or []]
    for row in reader:
        geoid = row["GEOID"].strip()
        coords[(geoid[:2], geoid[2:])] = (row["INTPTLAT"].strip(), row["INTPTLONG"].strip())
    return coords


def build_municipalities(
    subest_raw: bytes,
    gazetteer_raw: bytes,
    county_names: dict[tuple[str, str], str],
) -> list[tuple[str, str, str, str, str, str]]:
    """Place rows ``(usps, municipality, county, population, latitude, longitude)``."""
    subest = _rows(subest_raw)
    primary = _primary_county(subest)
    coords = _place_coords(gazetteer_raw)
    rows: list[tuple[str, str, str, str, str, str]] = []
    for row in subest:
        if row["SUMLEV"] != "162":
            continue
        place = (row["STATE"], row["PLACE"])
        usps = FIPS_TO_USPS.get(row["STATE"])
        county_fips = primary.get(place)
        point = coords.get(place)
        if usps is None or county_fips is None or point is None:
            continue
        county = county_names.get((row["STATE"], county_fips))
        if county is None:
            continue
        rows.append((usps, row["NAME"], county, row[POP_FIELD], point[0], point[1]))
    return rows


def _write(path: Path, header: list[str], rows: list[tuple[str, ...]]) -> None:
    """Write a CSV with ``header`` and ``rows`` to ``path``."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(sorted(rows))


def main() -> None:
    """Download the Census sources, join them, and write the municipality CSV."""
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    names_by_fips = county_names(_fetch(COUNTY_URL))
    municipality_rows = build_municipalities(_fetch(SUBEST_URL), _fetch(GAZ_URL), names_by_fips)
    _write(
        REFERENCE_DIR / "municipalities.csv",
        ["state", "municipality", "county", "population", "latitude", "longitude"],
        municipality_rows,
    )
    print(f"municipalities: {len(municipality_rows)} rows")


if __name__ == "__main__":
    main()
