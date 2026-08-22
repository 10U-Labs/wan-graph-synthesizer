from __future__ import annotations

import re
from typing import Any

from synthesizer.input_graph import FiberSegment, Site, SiteInfo, link_key, haversine_miles

PROVIDER_KIND = "provider region"
CARRIER_KIND = "PoP"
SITE_KIND = "Tenant site"
OFF_NET_KIND = "Off-net site"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "x"


def _city(row: dict[str, Any]) -> str:
    region = row["state"] if row["country"] == "United States" else row["country"]
    return f"{row['municipality']}, {region}"


def _unique(base: str, used: set[str]) -> str:
    site_id = base
    suffix = 2
    while site_id in used:
        site_id = f"{base}-{suffix}"
        suffix += 1
    used.add(site_id)
    return site_id


def _yes(value: Any) -> bool:
    return str(value or "").strip().lower() == "yes"


def _place(row: dict[str, Any], site_id: str, name: str, kind: str) -> Site:
    return Site(
        id=site_id,
        name=name,
        kind=kind,
        coords=(float(row["latitude"]), float(row["longitude"])),
        info=SiteInfo(
            municipality=row["municipality"], state=row["state"], country=row["country"]
        ),
        exempt_from_distance_constraint=_yes(row.get("exemptfromdistanceconstraint")),
    )


def _load_places(rows: list[dict[str, Any]], prefix: str, kind: str, named: bool) -> list[Site]:
    used: set[str] = set()
    places: list[Site] = []
    for row in rows:
        name = row["name"] if named else _city(row)
        site_id = _unique(f"{prefix}-{_slug(name)}", used)
        places.append(_place(row, site_id, name, kind))
    return places


def load_regions(rows: list[dict[str, Any]]) -> list[Site]:
    return _load_places(rows, "provider", PROVIDER_KIND, named=True)


def load_sites(rows: list[dict[str, Any]]) -> list[Site]:
    return _load_places(rows, "site", SITE_KIND, named=True)


def load_off_net(rows: list[dict[str, Any]]) -> list[Site]:
    return _load_places(rows, "offnet", OFF_NET_KIND, named=False)


def load_merged_carriers(
    site_rows: list[dict[str, Any]], link_rows: list[dict[str, Any]]
) -> tuple[list[Site], dict[tuple[str, str], FiberSegment]]:
    used: set[str] = set()
    pops: list[Site] = []
    by_city: dict[tuple[str, str], Site] = {}
    for row in site_rows:
        city = (row["municipality"], row["state"])
        if city in by_city:
            continue
        name = _city(row)
        site = _place(row, _unique(_slug(name), used), name, CARRIER_KIND)
        pops.append(site)
        by_city[city] = site
    links: dict[tuple[str, str], FiberSegment] = {}
    owners_by_key: dict[tuple[str, str], set[str]] = {}
    under_water: set[tuple[str, str]] = set()
    connected: set[str] = set()
    for row in link_rows:
        source = by_city.get((row["a_municipality"], row["a_state"]))
        target = by_city.get((row["z_municipality"], row["z_state"]))
        if source is None or target is None or source.id == target.id:
            continue
        key = link_key(source.id, target.id)
        if row.get("carrier"):
            owners_by_key.setdefault(key, set()).add(str(row["carrier"]))
        if row.get("submarine"):
            under_water.add(key)
        links[key] = FiberSegment(
            source=key[0], target=key[1], distance_miles=haversine_miles(source, target),
            carriers=frozenset(owners_by_key.get(key, ())),
            submarine=key in under_water,
        )
        connected.update(key)
    pops = [site for site in by_city.values() if site.id in connected]
    return pops, links
