#!/usr/bin/env python3
"""Build the county-to-metro crosswalk CSV from public Census flat files.

Run once to (re)generate ``data/reference/county_metros.csv``; the committed CSV
is the artifact the designer reads at runtime (this script never runs in CI). It
maps each county to its Census metropolitan area (CBSA) and that metro's official
population, so the designer can rank a state's metros and pick anchor cities. Two
public Census sources (both 2023 vintage, to stay consistent with the county and
municipality reference CSVs) are joined by county FIPS:

* CBSA membership, titles, metro/micropolitan class, and metro populations --
  ``cbsa-est2023-alldata.csv`` (CBSA and county rows distinguished by ``LSAD``)
* authoritative county names -- ``co-est2023-alldata.csv`` (SUMLEV 050 ``CTYNAME``),
  the same source ``municipalities.csv`` uses, so the names join exactly

Only Metropolitan Statistical Areas are kept; Micropolitan areas are dropped.
Census files are Latin-1.
"""

from __future__ import annotations

import csv
import io
import urllib.request
from pathlib import Path

COUNTY_URL = (
    "https://www2.census.gov/programs-surveys/popest/datasets/"
    "2020-2023/counties/totals/co-est2023-alldata.csv"
)
CBSA_URL = (
    "https://www2.census.gov/programs-surveys/popest/datasets/"
    "2020-2023/metro/totals/cbsa-est2023-alldata.csv"
)

REFERENCE_DIR = Path("data/reference")
POP_FIELD = "POPESTIMATE2023"
METRO_LSAD = "Metropolitan Statistical Area"
COUNTY_LSAD = "County or equivalent"

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


def county_names(raw: bytes) -> dict[str, str]:
    """Map 5-digit county FIPS to its authoritative ``CTYNAME`` (SUMLEV 050)."""
    return {
        row["STATE"] + row["COUNTY"]: row["CTYNAME"]
        for row in _rows(raw)
        if row["SUMLEV"] == "050"
    }


def metropolitan_cbsas(rows: list[dict[str, str]]) -> dict[str, tuple[str, int]]:
    """Map each Metropolitan Statistical Area's CBSA code to ``(title, population)``.

    The CBSA total sits on the header row (no county FIPS, no metro division);
    Micropolitan areas and metropolitan-division headers are excluded.
    """
    metros: dict[str, tuple[str, int]] = {}
    for row in rows:
        if row["STCOU"] or row["MDIV"] or row["LSAD"] != METRO_LSAD:
            continue
        metros[row["CBSA"]] = (row["NAME"], int(row[POP_FIELD]))
    return metros


def crosswalk_rows(
    cbsa_raw: bytes, names_by_fips: dict[str, str]
) -> list[tuple[str, str, str, str, str]]:
    """Rows ``(usps, county, cbsa_code, cbsa_title, cbsa_population)`` for metro counties."""
    rows = _rows(cbsa_raw)
    metros = metropolitan_cbsas(rows)
    seen: set[str] = set()
    out: list[tuple[str, str, str, str, str]] = []
    for row in rows:
        if not row["STCOU"] or row["LSAD"] != COUNTY_LSAD or row["CBSA"] not in metros:
            continue
        # CBSA-file county FIPS drop the leading zero (e.g. "1073"); pad to 5 digits
        # so they join the zero-padded county-name index.
        fips = row["STCOU"].zfill(5)
        if fips in seen:
            continue
        usps = FIPS_TO_USPS.get(fips[:2])
        county = names_by_fips.get(fips)
        if usps is None or county is None:
            continue
        seen.add(fips)
        title, population = metros[row["CBSA"]]
        out.append((usps, county, row["CBSA"], title, str(population)))
    return out


def _write(path: Path, header: list[str], rows: list[tuple[str, ...]]) -> None:
    """Write a CSV with ``header`` and ``rows`` (sorted) to ``path``."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(sorted(rows))


def main() -> None:
    """Download the Census sources, join them, and write the crosswalk CSV."""
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    names_by_fips = county_names(_fetch(COUNTY_URL))
    rows = crosswalk_rows(_fetch(CBSA_URL), names_by_fips)
    _write(
        REFERENCE_DIR / "county_metros.csv",
        ["state", "county", "cbsa_code", "cbsa_title", "cbsa_population"],
        rows,
    )
    print(f"county_metros: {len(rows)} rows across {len({r[2] for r in rows})} metros")


if __name__ == "__main__":
    main()
