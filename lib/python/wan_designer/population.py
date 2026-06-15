"""Population-anchored core and aggregation placement.

The optimizer decides *which* states warrant a core and seats aggregations from
access demand; this module fixes *where* those nodes land. Per state a core may
only sit in the most-populous municipality of the most-populous county, and a
state that holds an access node is given two aggregations -- the most-populous
municipalities of its two most-populous counties. The chosen city need not host
a carrier PoP: when none exists the node is synthesized as a greenfield PoP whose
backbone links are tagged for procurement, so the design still meshes and routes.

Population figures come from the Census reference CSVs under ``data/reference``;
nothing here reads the network. Operator force-pins remain a separate concern.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from wan_designer.model import (
    KIND_POP,
    PhysicalEdge,
    Vertex,
    VertexInfo,
    edge_key,
    haversine_miles,
    is_carrier_pop,
    slugify,
)

GREENFIELD_TENANT = "Greenfield"
GREENFIELD_BACKBONE_LINKS = 3
PROCURED_EDGE_NOTE = "to-be-procured population-anchor backbone link"
GREENFIELD_DESCRIPTION = "Greenfield population anchor; backbone connectivity to be procured"

# Census place and county names carry a designator word ("city", "County", ...)
# that the carrier PoP municipality strings omit; dropping it lets the two join.
_DESIGNATORS = frozenset(
    {
        "city",
        "town",
        "township",
        "village",
        "borough",
        "municipality",
        "county",
        "parish",
        "cdp",
        "metro",
        "government",
        "unified",
        "consolidated",
        "urban",
    }
)


def normalize_place(name: str) -> str:
    """Canonical key for joining a municipality or county name across sources."""
    lowered = name.lower().replace(".", " ").replace("saint ", "st ")
    words = [word for word in re.split(r"[^a-z0-9]+", lowered) if word]
    kept = [word for word in words if word not in _DESIGNATORS]
    return " ".join(kept or words)


@dataclass(frozen=True)
class MunicipalityRow:
    """One Census place: its name, state, county key, population, and location."""

    municipality: str
    state: str
    county_key: str
    population: int
    coords: tuple[float, float]


def load_county_populations(path: Path) -> dict[tuple[str, str], int]:
    """Map ``(state, county_key)`` to county population from the reference CSV."""
    populations: dict[tuple[str, str], int] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            populations[(row["state"].strip(), normalize_place(row["county"]))] = int(
                row["population"]
            )
    return populations


def load_municipalities(path: Path) -> list[MunicipalityRow]:
    """Load Census places (municipalities) from the reference CSV."""
    rows: list[MunicipalityRow] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                MunicipalityRow(
                    municipality=row["municipality"].strip(),
                    state=row["state"].strip(),
                    county_key=normalize_place(row["county"]),
                    population=int(row["population"]),
                    coords=(float(row["latitude"]), float(row["longitude"])),
                )
            )
    return rows


@dataclass(frozen=True)
class Anchor:
    """A populous city chosen to host a core or aggregation node."""

    municipality: str
    state: str
    coords: tuple[float, float]
    existing_pop_id: str | None


@dataclass(frozen=True)
class StatePlacement:
    """A state's population picks: its core city and its one or two aggregations."""

    state: str
    core: Anchor
    aggregations: tuple[Anchor, ...]
    requires_aggregations: bool


def carrier_states(carrier_pops: list[Vertex]) -> set[str]:
    """The states that hold a carrier PoP -- the default anchoring scope."""
    return {pop.info.state for pop in carrier_pops if pop.info.state}


def _nearest_state(access: Vertex, carrier_pops: list[Vertex]) -> str:
    """The state of the carrier PoP nearest an access vertex."""
    return min(carrier_pops, key=lambda pop: haversine_miles(access, pop)).info.state


def access_states(access_vertices: list[Vertex], carrier_pops: list[Vertex]) -> set[str]:
    """States holding an access node, by its own state or its nearest PoP's."""
    states: set[str] = set()
    for access in access_vertices:
        if access.info.state:
            states.add(access.info.state)
        elif carrier_pops:
            states.add(_nearest_state(access, carrier_pops))
    states.discard("")
    return states


def _ranked_counties(state: str, county_pops: dict[tuple[str, str], int]) -> list[str]:
    """County keys in ``state``, most populous first; name breaks ties."""
    counties = [(pop, key) for (st, key), pop in county_pops.items() if st == state]
    return [key for _pop, key in sorted(counties, key=lambda item: (-item[0], item[1]))]


def _ranked_municipalities(
    state: str, county_key: str, muni_rows: list[MunicipalityRow]
) -> list[MunicipalityRow]:
    """Municipalities of one county, most populous first; name breaks ties."""
    members = [row for row in muni_rows if row.state == state and row.county_key == county_key]
    return sorted(members, key=lambda row: (-row.population, normalize_place(row.municipality)))


def _two_cities(
    state: str, counties: list[str], muni_rows: list[MunicipalityRow]
) -> list[MunicipalityRow]:
    """City A and City B: top municipality of the state's two most-populous counties.

    With a single populous county (or an empty second one), City B falls back to
    that county's second-largest municipality, honoring the two-aggregation rule.
    """
    primary = _ranked_municipalities(state, counties[0], muni_rows)
    if not primary:
        return []
    if len(counties) >= 2:
        secondary = _ranked_municipalities(state, counties[1], muni_rows)
        if secondary:
            return [primary[0], secondary[0]]
    return [primary[0], primary[1]] if len(primary) >= 2 else [primary[0]]


def _pop_id_by_place(carrier_pops: list[Vertex]) -> dict[tuple[str, str], str]:
    """Index carrier PoPs by ``(municipality_key, state)`` for anchor reuse."""
    index: dict[tuple[str, str], str] = {}
    for pop in carrier_pops:
        if pop.info.municipality and pop.info.state:
            index[(normalize_place(pop.info.municipality), pop.info.state)] = pop.id
    return index


def _anchor(row: MunicipalityRow, pop_index: dict[tuple[str, str], str]) -> Anchor:
    """Build an anchor for a chosen city, noting any co-located carrier PoP."""
    existing = pop_index.get((normalize_place(row.municipality), row.state))
    return Anchor(row.municipality, row.state, row.coords, existing)


def population_placements(
    carrier_pops: list[Vertex],
    access: set[str],
    county_pops: dict[tuple[str, str], int],
    muni_rows: list[MunicipalityRow],
    states: set[str],
) -> list[StatePlacement]:
    """Resolve each in-scope state's core city and aggregation cities."""
    pop_index = _pop_id_by_place(carrier_pops)
    placements: list[StatePlacement] = []
    for state in sorted(states):
        counties = _ranked_counties(state, county_pops)
        if not counties:
            continue
        cities = _two_cities(state, counties, muni_rows)
        if not cities:
            continue
        anchors = tuple(_anchor(row, pop_index) for row in cities)
        placements.append(
            StatePlacement(state, anchors[0], anchors, state in access)
        )
    return placements


@dataclass(frozen=True)
class RealizedAnchors:
    """Population anchors realized into the graph as concrete vertices and edges.

    ``core_anchor_ids`` are every in-scope state's City A -- the only place a core
    may sit there, offered to the optimizer as candidates (never forced).
    ``required_aggregation_ids`` are the City A and City B nodes of access-bearing
    states, which must be seated. A City A that is in both sets is co-located: the
    optimizer splits it into a core candidate and an aggregation twin downstream.
    """

    vertices: list[Vertex]
    physical_edges: dict[tuple[str, str], PhysicalEdge]
    core_anchor_ids: frozenset[str]
    required_aggregation_ids: frozenset[str]


def _anchor_key(anchor: Anchor) -> tuple[str, str]:
    """The ``(municipality_key, state)`` identity shared by a city's anchors."""
    return (normalize_place(anchor.municipality), anchor.state)


def _greenfield_vertex(anchor: Anchor, vertex_id: str) -> Vertex:
    """A synthesized carrier PoP standing in for an anchor city without one."""
    return Vertex(
        id=vertex_id,
        name=f"{anchor.municipality}, {anchor.state}",
        tenant=GREENFIELD_TENANT,
        kind=KIND_POP,
        coords=anchor.coords,
        info=VertexInfo(
            description=GREENFIELD_DESCRIPTION,
            municipality=anchor.municipality,
            state=anchor.state,
        ),
    )


def _unique_id(anchor: Anchor, used_ids: set[str]) -> str:
    """A greenfield vertex id that does not collide with an existing vertex id."""
    base = f"anchor_{slugify(f'{anchor.municipality}_{anchor.state}')}"
    vertex_id = base
    suffix = 2
    while vertex_id in used_ids:
        vertex_id = f"{base}_{suffix}"
        suffix += 1
    return vertex_id


def _procured_edges(
    vertex: Vertex, existing_pops: list[Vertex]
) -> dict[tuple[str, str], PhysicalEdge]:
    """To-be-procured backbone links from a greenfield node to its nearest PoPs."""
    nearest = sorted(existing_pops, key=lambda pop: haversine_miles(vertex, pop))
    edges: dict[tuple[str, str], PhysicalEdge] = {}
    for pop in nearest[:GREENFIELD_BACKBONE_LINKS]:
        key = edge_key(vertex.id, pop.id)
        edges[key] = PhysicalEdge(
            source=key[0],
            target=key[1],
            distance_miles=haversine_miles(vertex, pop),
            note=PROCURED_EDGE_NOTE,
        )
    return edges


@dataclass
class _Realization:
    """Mutable accumulator while seating anchors as concrete graph vertices."""

    existing_pops: list[Vertex]
    used_ids: set[str]
    vertices: list[Vertex]
    physical_edges: dict[tuple[str, str], PhysicalEdge]
    by_key: dict[tuple[str, str], str]


def _begin_realization(
    vertices: list[Vertex], physical_edges: dict[tuple[str, str], PhysicalEdge]
) -> _Realization:
    """Start an accumulator carrying the current graph and the ids already in use."""
    return _Realization(
        existing_pops=[vertex for vertex in vertices if is_carrier_pop(vertex)],
        used_ids={vertex.id for vertex in vertices},
        vertices=list(vertices),
        physical_edges=dict(physical_edges),
        by_key={},
    )


def _resolve_anchor(realization: _Realization, anchor: Anchor) -> str:
    """The vertex id realizing ``anchor``, synthesizing a greenfield node once."""
    key = _anchor_key(anchor)
    if key in realization.by_key:
        return realization.by_key[key]
    if anchor.existing_pop_id is not None:
        realization.by_key[key] = anchor.existing_pop_id
        return anchor.existing_pop_id
    vertex_id = _unique_id(anchor, realization.used_ids)
    realization.used_ids.add(vertex_id)
    vertex = _greenfield_vertex(anchor, vertex_id)
    realization.vertices.append(vertex)
    realization.physical_edges.update(_procured_edges(vertex, realization.existing_pops))
    realization.by_key[key] = vertex_id
    return vertex_id


def realize_anchors(
    placements: list[StatePlacement],
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> RealizedAnchors:
    """Seat every placement's anchors into the graph and collect their role ids."""
    realization = _begin_realization(vertices, physical_edges)
    core_ids: set[str] = set()
    required_ids: set[str] = set()
    for placement in placements:
        core_ids.add(_resolve_anchor(realization, placement.core))
        if placement.requires_aggregations:
            for anchor in placement.aggregations:
                required_ids.add(_resolve_anchor(realization, anchor))
    return RealizedAnchors(
        realization.vertices,
        realization.physical_edges,
        frozenset(core_ids),
        frozenset(required_ids),
    )
