"""Synthesize aggregation facilities for operator-forced installations.

An installation carries no fiber of its own, so unaided it can only be demand. An
installation is promoted to an aggregation only when the operator explicitly forces
it (its name appears in ``forced_aggregations``); it is never auto-selected, though
once forced its twin may also win a core slot. To let a forced installation serve as
an aggregation point we stand
up a co-located carrier-PoP *twin* at its coordinates, wired by synthetic local
fiber to the nearest existing carrier PoPs (see :mod:`wan_designer.local_fiber`).
The twin's name matches the installation, so the operator's force-pin resolves onto
it; it then flows through the unchanged dual-homing machinery while the original
installation stays an access/demand vertex that homes to its own twin plus one
neighbor.

Co-located forced sites (e.g. Hill AFB and Ogden ALC sharing one location)
collapse to a single twin. A site with fewer than two distinct carrier PoPs
within :data:`~wan_designer.local_fiber.LOCAL_FIBER_RADIUS_MILES` cannot be
biconnected into the backbone, so it is left demand-only rather than seated as a
fragile single-homed facility -- that radius admits every contiguous-US
installation while excluding off-continent sites (e.g. an Alaska base) that have no
nearby backbone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from wan_designer.local_fiber import (
    LOCAL_FIBER_MIN_LINKS,
    LOCAL_FIBER_RADIUS_MILES,
    build_local_fiber_twin,
    unique_twin_id,
)
from wan_designer.model import (
    PhysicalEdge,
    Vertex,
    is_carrier_pop,
    is_justified_aggregation,
)

logger = logging.getLogger(__name__)

FACILITY_ID_PREFIX = "fac_"
FACILITY_EDGE_NOTE = "synthetic installation aggregation backbone link"


@dataclass(frozen=True)
class RealizedInstallations:
    """Justified installations realized into the graph as aggregation facilities.

    ``vertices`` and ``physical_edges`` are the graph augmented with one co-located
    twin PoP per realized installation and its synthetic backbone links;
    ``facility_ids`` are those twins' ids. Each twin is seated as a forced
    aggregation via the operator's force-pin, and may also win a core slot.
    """

    vertices: list[Vertex]
    physical_edges: dict[tuple[str, str], PhysicalEdge]
    facility_ids: frozenset[str]


def _coord_key(vertex: Vertex) -> tuple[float, float]:
    """A rounded coordinate identity, so co-located sites collapse to one twin."""
    return (round(vertex.lat, 4), round(vertex.lon, 4))


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
    :data:`~wan_designer.local_fiber.LOCAL_FIBER_RADIUS_MILES` is skipped (it stays
    demand-only).
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
        twin_id = unique_twin_id(f"{FACILITY_ID_PREFIX}{installation.id}", used_ids)
        built = build_local_fiber_twin(
            installation, twin_id, carrier_pops, note=FACILITY_EDGE_NOTE, shown_in_map=False
        )
        if built is None:
            logger.info(
                "Installation %s has fewer than %d carrier PoPs within %.0f mi; "
                "leaving it demand-only",
                installation.id,
                LOCAL_FIBER_MIN_LINKS,
                LOCAL_FIBER_RADIUS_MILES,
            )
            continue
        twin, edges = built
        used_ids.add(twin_id)
        augmented_vertices.append(twin)
        augmented_edges.update(edges)
        facility_ids.add(twin_id)
    return RealizedInstallations(augmented_vertices, augmented_edges, frozenset(facility_ids))
