"""Fabricate on-net nodes for operator-forced locations missing from our data.

A location carries no fiber of its own in our data, so unaided it can only be demand.
But we only hold *public* carrier data; real fiber exists everywhere. So when the
operator forces a location to serve as an aggregation point, we honour it by
fabricating the node our data is missing: a co-located carrier-PoP *twin* at the
location's coordinates, spliced on-net with synthetic local fiber to the nearest
carrier PoPs (see :mod:`wan_designer.local_fiber`). The twin's name matches the
location, so the operator's force-pin resolves onto it; it then flows through the
unchanged dual-homing machinery while the original location stays an access/demand
vertex homing to its own twin plus its neighbours.

A force always wins: the twin is wired to its nearest carrier PoPs *regardless of
distance* (no radius cap), so a forced location is never silently dropped to
demand-only for want of nearby public fiber. Co-located forced sites (e.g. Hill AFB
and Ogden ALC sharing one location) collapse to a single twin.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from wan_designer.local_fiber import (
    LOCAL_FIBER_MIN_LINKS,
    build_local_fiber_twin,
    unique_twin_id,
)
from wan_graph.model import (
    PhysicalEdge,
    Vertex,
    is_carrier_pop,
)

logger = logging.getLogger(__name__)

ON_NET_ID_PREFIX = "fac_"
ON_NET_EDGE_NOTE = "synthetic on-net fabrication backbone link"


@dataclass(frozen=True)
class FabricatedOnNetNodes:
    """Forced locations fabricated into the graph as on-net aggregation nodes.

    ``vertices`` and ``physical_edges`` are the graph augmented with one co-located
    twin PoP per fabricated location and its synthetic backbone links; ``on_net_ids``
    are those twins' ids. Each twin is seated as a forced aggregation via the
    operator's force-pin, and may also win a core slot.
    """

    vertices: list[Vertex]
    physical_edges: dict[tuple[str, str], PhysicalEdge]
    on_net_ids: frozenset[str]


def _coord_key(vertex: Vertex) -> tuple[float, float]:
    """A rounded coordinate identity, so co-located sites collapse to one twin."""
    return (round(vertex.lat, 4), round(vertex.lon, 4))


def fabricate_missing_on_net_nodes(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    forced_aggregation_names: frozenset[str] = frozenset(),
) -> FabricatedOnNetNodes:
    """Fabricate an on-net twin for every operator-forced non-carrier location.

    A location the operator named in ``forced_aggregation_names`` is fabricated on-net
    whether or not our data marks it justified -- forcing alone is sufficient, since
    any place can become a hub. Carrier PoPs named here are already on-net and need no
    twin. Forced locations are taken in a stable id order; co-located sites yield a
    single twin. The twin always wires to its nearest carrier PoPs regardless of
    distance, so a forced location is dropped only in the degenerate case of fewer
    than :data:`LOCAL_FIBER_MIN_LINKS` carrier PoPs existing at all.
    """
    carrier_pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    used_ids = {vertex.id for vertex in vertices}
    augmented_vertices = list(vertices)
    augmented_edges = dict(physical_edges)
    on_net_ids: set[str] = set()
    seen_coords: set[tuple[float, float]] = set()
    for location in sorted(
        (
            vertex for vertex in vertices
            if not is_carrier_pop(vertex) and vertex.name in forced_aggregation_names
        ),
        key=lambda vertex: vertex.id,
    ):
        coord_key = _coord_key(location)
        if coord_key in seen_coords:
            continue
        seen_coords.add(coord_key)
        twin_id = unique_twin_id(f"{ON_NET_ID_PREFIX}{location.id}", used_ids)
        built = build_local_fiber_twin(
            location, twin_id, carrier_pops,
            note=ON_NET_EDGE_NOTE, shown_in_map=False, max_radius=None,
        )
        if built is None:
            logger.info(
                "Location %s has fewer than %d carrier PoPs to wire to; "
                "leaving it demand-only",
                location.id,
                LOCAL_FIBER_MIN_LINKS,
            )
            continue
        twin, edges = built
        used_ids.add(twin_id)
        augmented_vertices.append(twin)
        augmented_edges.update(edges)
        on_net_ids.add(twin_id)
    return FabricatedOnNetNodes(augmented_vertices, augmented_edges, frozenset(on_net_ids))
