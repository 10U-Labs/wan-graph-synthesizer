"""Read the stored simple-shape JSON into the synthesizer's graph objects.

Each place is sent to the API as a bare geographic row -- ``municipality, state,
latitude, longitude`` (plus ``name`` for provider regions and tenant sites) -- and what it
*is* comes from the endpoint it was stored under, not from a column. These loaders turn
those rows into :class:`Site`/:class:`FiberSegment` objects, deriving
``kind``/``name`` from the source, generating ids, and resolving carrier
fiber segments (listed by the two endpoints' city+state) to the points they name.
"""

from __future__ import annotations

import re
from typing import Any

from synthesizer.input_graph import FiberSegment, Site, SiteInfo, link_key, haversine_miles

PROVIDER_KIND = "provider region"
CARRIER_KIND = "PoP"
SITE_KIND = "Tenant site"
OFF_NET_KIND = "Off-net site"


def _slug(value: str) -> str:
    """A lowercase hyphen-separated id fragment from arbitrary text."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "x"


def _city(row: dict[str, Any]) -> str:
    """The ``City, Region`` display name of a row (also how forced pins are written).

    Region is the 2-letter state for US places (so ``City, ST`` is unchanged and forced
    pins keep matching) and the country for everywhere else (``Tokyo, Japan``).
    """
    region = row["state"] if row["country"] == "United States" else row["country"]
    return f"{row['municipality']}, {region}"


def _unique(base: str, used: set[str]) -> str:
    """``base`` if free, else ``base-2``/``base-3``/... so every id is distinct."""
    site_id = base
    suffix = 2
    while site_id in used:
        site_id = f"{base}-{suffix}"
        suffix += 1
    used.add(site_id)
    return site_id


def _yes(value: Any) -> bool:
    """Parse a ``Yes``/``No`` cell (case-insensitively) into a bool; absent or blank is False."""
    return str(value or "").strip().lower() == "yes"


def _place(row: dict[str, Any], site_id: str, name: str, kind: str) -> Site:
    """Build one site from a geographic row with its derived role attributes.

    Tenant-site rows carry an ``ExemptFromDistanceConstraint`` (``Yes``/``No``) column;
    carrier, cloud-region and off-net rows have none, so absence reads as not exempt.
    """
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
    """Load demand sites (provider regions, tenant sites, off-net) from simple rows.

    ``named`` rows carry their own ``name``; the rest are named by their ``City, ST``.
    """
    used: set[str] = set()
    places: list[Site] = []
    for row in rows:
        name = row["name"] if named else _city(row)
        site_id = _unique(f"{prefix}-{_slug(name)}", used)
        places.append(_place(row, site_id, name, kind))
    return places


def load_regions(rows: list[dict[str, Any]]) -> list[Site]:
    """Provider regions, named, coloured by kind on the map."""
    return _load_places(rows, "provider", PROVIDER_KIND, named=True)


def load_sites(rows: list[dict[str, Any]]) -> list[Site]:
    """A tenant's own access sites, named."""
    return _load_places(rows, "site", SITE_KIND, named=True)


def load_off_net(rows: list[dict[str, Any]]) -> list[Site]:
    """Off-net candidate sites, named by their city (used to fabricate twins)."""
    return _load_places(rows, "offnet", OFF_NET_KIND, named=False)


def load_merged_carriers(
    site_rows: list[dict[str, Any]], link_rows: list[dict[str, Any]]
) -> tuple[list[Site], dict[tuple[str, str], FiberSegment]]:
    """Load the merged carriers: one point per city, plus the fiber between them.

    The cleaned data keys carrier points by city, so colocated points from different
    carriers are one backbone node; every carrier's fiber segments (listed by their two
    endpoints' city+state) resolve against that shared, city-keyed set. Distance is the
    great-circle miles between the resolved points. Segments within a single city
    (self-loops) and segments naming a city no carrier serves (dangling) are dropped.

    Two carriers with fiber between the same two cities are one segment naming both of
    them, rather than the second row replacing the first. The distance is the same either
    way -- it is the great-circle miles between two cities -- and who has fiber there is
    what says whether a path across it can be ordered whole (see
    :func:`synthesizer.input_graph.carriers_along`).
    """
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
    connected: set[str] = set()
    for row in link_rows:
        source = by_city.get((row["a_municipality"], row["a_state"]))
        target = by_city.get((row["z_municipality"], row["z_state"]))
        if source is None or target is None or source.id == target.id:
            continue
        key = link_key(source.id, target.id)
        if row.get("carrier"):
            owners_by_key.setdefault(key, set()).add(str(row["carrier"]))
        links[key] = FiberSegment(
            source=key[0], target=key[1], distance_miles=haversine_miles(source, target),
            carriers=frozenset(owners_by_key.get(key, ())),
        )
        connected.update(key)
    # A point no surviving segment touches is not a usable backbone node; drop it so
    # the merged carriers' points and their fiber stay consistent.
    pops = [site for site in by_city.values() if site.id in connected]
    return pops, links
