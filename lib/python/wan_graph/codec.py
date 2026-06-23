"""Read the stored simple-shape JSON into the synthesizer's graph objects.

Each place is sent to the API as a bare geographic row -- ``municipality, state,
latitude, longitude`` (plus ``name`` for cloud regions and tenant sites) -- and what it
*is* comes from the endpoint it was stored under, not from a column. These loaders turn
those rows into :class:`wan_graph.model.Vertex`/:class:`PhysicalEdge` objects, deriving
``kind``/``name``/``shown_in_map`` from the source, generating ids, and resolving carrier
connections (listed by the two endpoints' city+state) to the points they name.
"""

from __future__ import annotations

import re
from typing import Any

from wan_graph.model import PhysicalEdge, Vertex, VertexInfo, edge_key, haversine_miles

CSP_KIND = "CSP data center"
CARRIER_KIND = "PoP"
SITE_KIND = "Tenant site"
OFF_NET_KIND = "Off-net site"


def _slug(value: str) -> str:
    """A lowercase hyphen-separated id fragment from arbitrary text."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "x"


def _city(row: dict[str, Any]) -> str:
    """The ``City, ST`` display name of a row (also how forced pins are written)."""
    return f"{row['municipality']}, {row['state']}"


def _unique(base: str, used: set[str]) -> str:
    """``base`` if free, else ``base-2``/``base-3``/... so every id is distinct."""
    vertex_id = base
    suffix = 2
    while vertex_id in used:
        vertex_id = f"{base}-{suffix}"
        suffix += 1
    used.add(vertex_id)
    return vertex_id


def _place(row: dict[str, Any], vertex_id: str, name: str, kind: str, shown: bool) -> Vertex:
    """Build one vertex from a geographic row with its derived role attributes."""
    return Vertex(
        id=vertex_id,
        name=name,
        kind=kind,
        coords=(float(row["latitude"]), float(row["longitude"])),
        info=VertexInfo(municipality=row["municipality"], state=row["state"]),
        shown_in_map=shown,
    )


def _load_places(rows: list[dict[str, Any]], prefix: str, kind: str, named: bool) -> list[Vertex]:
    """Load demand vertices (cloud regions, tenant sites, off-net) from simple rows.

    ``named`` rows carry their own ``name``; the rest are named by their ``City, ST``.
    """
    used: set[str] = set()
    places: list[Vertex] = []
    for row in rows:
        name = row["name"] if named else _city(row)
        vertex_id = _unique(f"{prefix}-{_slug(name)}", used)
        places.append(_place(row, vertex_id, name, kind, shown=True))
    return places


def load_regions(rows: list[dict[str, Any]]) -> list[Vertex]:
    """Cloud regions (CSP data centers), named, coloured by kind on the map."""
    return _load_places(rows, "csp", CSP_KIND, named=True)


def load_sites(rows: list[dict[str, Any]]) -> list[Vertex]:
    """A tenant's own access sites, named."""
    return _load_places(rows, "site", SITE_KIND, named=True)


def load_off_net(rows: list[dict[str, Any]]) -> list[Vertex]:
    """Off-net candidate sites, named by their city (used to fabricate twins)."""
    return _load_places(rows, "offnet", OFF_NET_KIND, named=False)


def load_substrate(
    vertex_rows: list[dict[str, Any]], edge_rows: list[dict[str, Any]]
) -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge]]:
    """Load the merged carrier substrate: one point per city, plus the fiber between them.

    The cleaned data keys carrier points by city, so colocated points from different
    carriers are one backbone node; every carrier's connections (listed by their two
    endpoints' city+state) resolve against that shared, city-keyed set. Distance is the
    great-circle miles between the resolved points. Connections within a single city
    (self-loops) and connections to a city no carrier serves (dangling) are dropped.
    """
    used: set[str] = set()
    pops: list[Vertex] = []
    by_city: dict[tuple[str, str], Vertex] = {}
    for row in vertex_rows:
        city = (row["municipality"], row["state"])
        if city in by_city:
            continue
        name = _city(row)
        vertex = _place(row, _unique(_slug(name), used), name, CARRIER_KIND, shown=False)
        pops.append(vertex)
        by_city[city] = vertex
    edges: dict[tuple[str, str], PhysicalEdge] = {}
    connected: set[str] = set()
    for row in edge_rows:
        source = by_city.get((row["a_municipality"], row["a_state"]))
        target = by_city.get((row["z_municipality"], row["z_state"]))
        if source is None or target is None or source.id == target.id:
            continue
        key = edge_key(source.id, target.id)
        edges[key] = PhysicalEdge(
            source=key[0], target=key[1], distance_miles=haversine_miles(source, target)
        )
        connected.update(key)
    # A point no surviving connection touches is not a usable backbone node; drop it so
    # the substrate's points and its fiber graph stay consistent.
    pops = [vertex for vertex in by_city.values() if vertex.id in connected]
    return pops, edges
