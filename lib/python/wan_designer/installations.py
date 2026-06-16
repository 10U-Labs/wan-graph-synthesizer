"""Synthesize aggregation facilities for operator-forced installations.

An installation carries no fiber of its own, so unaided it can only be demand. An
installation is promoted to an aggregation only when the operator explicitly forces
it (its name appears in ``forced_aggregations``); it is never auto-selected and
never a core. To let a forced installation serve as an aggregation point we stand
up a co-located carrier-PoP *twin* at its coordinates, wired by synthetic backbone
links to the nearest existing carrier PoPs. The twin's name matches the
installation, so the operator's force-pin resolves onto it; it then flows through
the unchanged dual-homing machinery while the original installation stays an
access/demand vertex that homes to its own twin plus one neighbor.

Co-located forced sites (e.g. Hill AFB and Ogden ALC sharing one location)
collapse to a single twin. A site with fewer than two distinct carrier PoPs
within :data:`FACILITY_RADIUS_MILES` cannot be biconnected into the backbone, so
it is left demand-only rather than seated as a fragile single-homed facility --
that radius admits every contiguous-US installation while excluding off-continent
sites (e.g. an Alaska base) that have no nearby backbone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from wan_designer.model import (
    KIND_POP,
    PhysicalEdge,
    Vertex,
    edge_key,
    haversine_miles,
    is_carrier_pop,
    is_justified_aggregation,
)

logger = logging.getLogger(__name__)

FACILITY_ID_PREFIX = "fac_"
FACILITY_BACKBONE_LINKS = 3
FACILITY_MIN_LINKS = 2
FACILITY_RADIUS_MILES = 300.0
FACILITY_EDGE_NOTE = "synthetic installation aggregation backbone link"


@dataclass(frozen=True)
class RealizedInstallations:
    """Justified installations realized into the graph as aggregation facilities.

    ``vertices`` and ``physical_edges`` are the graph augmented with one co-located
    twin PoP per realized installation and its synthetic backbone links;
    ``facility_ids`` are those twins' ids. Each twin is seated as a forced
    aggregation via the operator's force-pin (it is never a core candidate).
    """

    vertices: list[Vertex]
    physical_edges: dict[tuple[str, str], PhysicalEdge]
    facility_ids: frozenset[str]


def _coord_key(vertex: Vertex) -> tuple[float, float]:
    """A rounded coordinate identity, so co-located sites collapse to one twin."""
    return (round(vertex.lat, 4), round(vertex.lon, 4))


def nearest_carrier_pops(
    vertex: Vertex, carrier_pops: list[Vertex], links: int, max_radius: float
) -> list[Vertex]:
    """The up-to-``links`` nearest carrier PoPs within ``max_radius`` of ``vertex``."""
    ranked = sorted(
        ((haversine_miles(vertex, pop), pop) for pop in carrier_pops),
        key=lambda item: (item[0], item[1].id),
    )
    return [pop for distance, pop in ranked[:links] if distance <= max_radius]


def _facility_twin(installation: Vertex, vertex_id: str) -> Vertex:
    """A co-located carrier-PoP twin standing in for a justified installation."""
    return Vertex(
        id=vertex_id,
        name=installation.name,
        tenant=installation.tenant,
        kind=KIND_POP,
        coords=installation.coords,
        info=installation.info,
        shown_in_map=False,
    )


def _facility_edges(
    twin: Vertex, neighbors: list[Vertex]
) -> dict[tuple[str, str], PhysicalEdge]:
    """Synthetic backbone links from a facility twin to its nearest carrier PoPs."""
    edges: dict[tuple[str, str], PhysicalEdge] = {}
    for pop in neighbors:
        key = edge_key(twin.id, pop.id)
        edges[key] = PhysicalEdge(
            source=key[0],
            target=key[1],
            distance_miles=haversine_miles(twin, pop),
            note=FACILITY_EDGE_NOTE,
        )
    return edges


def _unique_facility_id(installation: Vertex, used_ids: set[str]) -> str:
    """A facility id derived from the installation that no vertex already uses."""
    base = f"{FACILITY_ID_PREFIX}{installation.id}"
    vertex_id = base
    suffix = 2
    while vertex_id in used_ids:
        vertex_id = f"{base}_{suffix}"
        suffix += 1
    return vertex_id


def realize_installations(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    forced_aggregation_names: frozenset[str] = frozenset(),
) -> RealizedInstallations:
    """Seat a co-located facility twin for every operator-forced justified installation.

    Only justified installations the operator has named in ``forced_aggregation_names``
    are realized -- an unforced installation stays demand-only, never an aggregation
    or a core. Forced installations are taken in a stable id order; co-located sites
    yield a single twin, and a site without two distinct carrier PoPs within
    :data:`FACILITY_RADIUS_MILES` is skipped (it stays demand-only).
    """
    carrier_pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    used_ids = {vertex.id for vertex in vertices}
    augmented_vertices = list(vertices)
    augmented_edges = dict(physical_edges)
    facility_ids: set[str] = set()
    seen_coords: set[tuple[float, float]] = set()
    for installation in sorted(
        (
            vertex for vertex in vertices
            if is_justified_aggregation(vertex) and vertex.name in forced_aggregation_names
        ),
        key=lambda vertex: vertex.id,
    ):
        coord_key = _coord_key(installation)
        if coord_key in seen_coords:
            continue
        seen_coords.add(coord_key)
        neighbors = nearest_carrier_pops(
            installation, carrier_pops, FACILITY_BACKBONE_LINKS, FACILITY_RADIUS_MILES
        )
        if len(neighbors) < FACILITY_MIN_LINKS:
            logger.info(
                "Installation %s has fewer than %d carrier PoPs within %.0f mi; "
                "leaving it demand-only",
                installation.id,
                FACILITY_MIN_LINKS,
                FACILITY_RADIUS_MILES,
            )
            continue
        vertex_id = _unique_facility_id(installation, used_ids)
        used_ids.add(vertex_id)
        twin = _facility_twin(installation, vertex_id)
        augmented_vertices.append(twin)
        augmented_edges.update(_facility_edges(twin, neighbors))
        facility_ids.add(vertex_id)
    return RealizedInstallations(augmented_vertices, augmented_edges, frozenset(facility_ids))
