"""Population-anchored core and aggregation placement.

The optimizer decides *which* states warrant a core and seats aggregations from
access demand; this module fixes *where* those nodes land, grouping a state's
cities by **metropolitan area** (a Census-defined CBSA). Per state a core may
only sit in the most-populous city of the most-populous metro. A state that holds
an access node is given two aggregations whose cities depend on whether it seats a
core: a cored state aggregates at its metro's *second* city and at the second
metro's top city; an un-cored state aggregates at its top metro city and the
second metro's top city. The chosen city need not host a carrier PoP: when none
exists the node is synthesized as a greenfield PoP whose backbone links are tagged
for procurement, so the design still meshes and routes.

Metro membership and official metro populations come from a Census CBSA crosswalk;
city populations and coordinates come from the municipality reference CSV (both
under ``data/reference``). Nothing here reads the network, and a metro is never
defined or sized by summing the municipalities we happen to hold -- its identity
and population are the Census's. Operator force-pins remain a separate concern.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from wan_designer.model import (
    KIND_POP,
    PhysicalEdge,
    StateAggregationSpec,
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


@dataclass(frozen=True)
class MetroRef:
    """The Census metro a county belongs to: its CBSA code and official population."""

    cbsa_code: str
    cbsa_population: int


def load_county_metros(path: Path) -> dict[tuple[str, str], MetroRef]:
    """Map ``(state, county_key)`` to its Census metro from the CBSA crosswalk CSV.

    The crosswalk holds only Metropolitan Statistical Area rows; a county absent
    from the map belongs to no metropolitan area. ``cbsa_population`` is the
    official Census metro population, the same value for every county in a CBSA.
    """
    metros: dict[tuple[str, str], MetroRef] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["state"].strip(), normalize_place(row["county"]))
            metros[key] = MetroRef(row["cbsa_code"].strip(), int(row["cbsa_population"]))
    return metros


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
    """A state's metro population picks: its core city and two aggregation slots.

    ``core`` is metro1.city1 (the only place a core may sit here). ``in_metro_second``
    is metro1.city2 -- the first aggregation *iff* this state seats a core.
    ``second_metro`` is metro2.city1 -- always the second aggregation. Either
    aggregation slot may be ``None`` for a state too thin to fill it.
    """

    state: str
    core: Anchor
    in_metro_second: Anchor | None
    second_metro: Anchor | None
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


@dataclass(frozen=True)
class Metro:
    """One metropolitan area within a state: its CBSA, population, and ranked cities.

    ``population`` is the official Census CBSA population (not a sum of ``cities``);
    ``cities`` are this state's municipalities in the metro, most populous first.
    """

    cbsa_code: str
    population: int
    cities: tuple[MunicipalityRow, ...]


def _state_metros(
    state: str,
    county_metros: dict[tuple[str, str], MetroRef],
    muni_rows: list[MunicipalityRow],
) -> list[Metro]:
    """Metros of ``state``, most populous first; CBSA code breaks population ties.

    Each municipality joins the metro of its county (via the crosswalk);
    municipalities whose county is in no metro are dropped. A metro is ranked by
    its official Census population and its cities are ordered by municipality
    population, name breaking ties.
    """
    members: dict[str, list[MunicipalityRow]] = {}
    populations: dict[str, int] = {}
    for row in muni_rows:
        if row.state != state:
            continue
        metro = county_metros.get((state, row.county_key))
        if metro is None:
            continue
        members.setdefault(metro.cbsa_code, []).append(row)
        populations[metro.cbsa_code] = metro.cbsa_population
    metros = [
        Metro(
            cbsa_code,
            populations[cbsa_code],
            tuple(
                sorted(rows, key=lambda row: (-row.population, normalize_place(row.municipality)))
            ),
        )
        for cbsa_code, rows in members.items()
    ]
    return sorted(metros, key=lambda metro: (-metro.population, metro.cbsa_code))


def _metro_city_slots(
    metros: list[Metro],
) -> tuple[MunicipalityRow, MunicipalityRow | None, MunicipalityRow | None]:
    """A state's three population slots: core city, in-metro second, second-metro.

    ``core`` is metro1.city1. ``in_metro_second`` (the cored first aggregation) is
    metro1.city2, falling back to metro2.city1 when metro1 has a single city; it
    never falls back to the core city, so it can never collide with a seated core.
    ``second_metro`` is metro2.city1, falling back to metro1.city2 when there is no
    second metro. Either aggregation slot is ``None`` when no city fills it.
    """
    core = metros[0].cities[0]
    metro1_second = metros[0].cities[1] if len(metros[0].cities) >= 2 else None
    metro2_first = metros[1].cities[0] if len(metros) >= 2 else None
    in_metro_second = metro1_second if metro1_second is not None else metro2_first
    second_metro = metro2_first if metro2_first is not None else metro1_second
    return core, in_metro_second, second_metro


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
    county_metros: dict[tuple[str, str], MetroRef],
    muni_rows: list[MunicipalityRow],
    states: set[str],
) -> list[StatePlacement]:
    """Resolve each in-scope state's core city and aggregation cities by metro."""
    pop_index = _pop_id_by_place(carrier_pops)
    placements: list[StatePlacement] = []
    for state in sorted(states):
        metros = _state_metros(state, county_metros, muni_rows)
        if not metros:
            continue
        core, in_metro_second, second_metro = _metro_city_slots(metros)
        placements.append(
            StatePlacement(
                state,
                _anchor(core, pop_index),
                _anchor(in_metro_second, pop_index) if in_metro_second is not None else None,
                _anchor(second_metro, pop_index) if second_metro is not None else None,
                state in access,
            )
        )
    return placements


@dataclass(frozen=True)
class RealizedAnchors:
    """Population anchors realized into the graph as concrete vertices and edges.

    ``core_anchor_ids`` are every in-scope state's metro1.city1 -- the only place a
    core may sit there, offered to the optimizer as candidates (never forced).
    ``aggregation_specs`` carries one :class:`StateAggregationSpec` per access state
    so the search can resolve its first aggregation per candidate core set (city2
    when the state seats a core, else city1). ``aggregation_candidate_ids`` is the
    union of every city any access state could seat, used to restrict the
    aggregation tier's candidate pool.
    """

    vertices: list[Vertex]
    physical_edges: dict[tuple[str, str], PhysicalEdge]
    core_anchor_ids: frozenset[str]
    aggregation_specs: tuple[StateAggregationSpec, ...]
    aggregation_candidate_ids: frozenset[str]


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
    """Seat every placement's anchors into the graph and collect their role ids.

    Every in-scope state's core city becomes a core candidate. Each access state
    additionally realizes its in-metro-second and second-metro cities and emits a
    :class:`StateAggregationSpec`; a city shared across slots is seated once.
    """
    realization = _begin_realization(vertices, physical_edges)
    core_ids: set[str] = set()
    specs: list[StateAggregationSpec] = []
    candidate_ids: set[str] = set()
    for placement in placements:
        core_id = _resolve_anchor(realization, placement.core)
        core_ids.add(core_id)
        if not placement.requires_aggregations:
            continue
        in_metro_second_id = (
            _resolve_anchor(realization, placement.in_metro_second)
            if placement.in_metro_second is not None
            else None
        )
        second_metro_id = (
            _resolve_anchor(realization, placement.second_metro)
            if placement.second_metro is not None
            else None
        )
        specs.append(
            StateAggregationSpec(placement.state, core_id, in_metro_second_id, second_metro_id)
        )
        candidate_ids.update(
            anchor_id
            for anchor_id in (core_id, in_metro_second_id, second_metro_id)
            if anchor_id is not None
        )
    return RealizedAnchors(
        realization.vertices,
        realization.physical_edges,
        frozenset(core_ids),
        tuple(specs),
        frozenset(candidate_ids),
    )
