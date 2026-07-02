"""Fabricate on-net nodes for operator-forced locations missing from our data.

A location carries no fiber of its own in our data, so unaided it can only be demand.
But we only hold *public* carrier data; real fiber exists everywhere. So when the
operator forces a location to serve as a backbone node, we honour it by
fabricating the node our data is missing: a co-located carrier-PoP *twin* at the
location's coordinates, spliced on-net with synthetic local fiber to the nearest
carrier PoPs (see :mod:`synthesizer.local_fiber`). The twin's name matches the
location, so the operator's force-pin resolves onto it; it then flows through the
unchanged backbone machinery while the original location stays an access/demand
vertex homing to its own twin plus its neighbours.

A force always wins -- but only at a data-center city: the twin is wired to its
nearest carrier PoPs *regardless of distance* (no radius cap), yet a forced location
whose city is not a data-center city is rejected, because the backbone gate is
absolute. Co-located forced sites (e.g. Hill AFB and Ogden ALC sharing one location)
collapse to a single twin.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from synthesizer.local_fiber import (
    LOCAL_FIBER_MIN_LINKS,
    LocalFiberTwinSpec,
    build_local_fiber_twin,
    unique_twin_id,
)
from synthesizer.model import backbone_city_allowed, is_carrier_pop
from synthesizer.input_graph import PhysicalEdge, Vertex

logger = logging.getLogger(__name__)

ON_NET_ID_PREFIX = "fac_"
ON_NET_EDGE_NOTE = "synthetic on-net fabrication backbone link"


@dataclass(frozen=True)
class FabricatedOnNetNodes:
    """Forced locations fabricated into the graph as on-net backbone nodes.

    ``vertices`` and ``physical_edges`` are the graph augmented with one co-located
    twin PoP per fabricated location and its synthetic backbone links; ``on_net_ids``
    are those twins' ids. Each twin is seated as a forced backbone node via the
    operator's force-pin.
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
    forced_backbone_names: frozenset[str] = frozenset(),
    datacenter_cities: frozenset[tuple[str, str]] = frozenset(),
    restrict: bool = True,
) -> FabricatedOnNetNodes:
    """Fabricate an on-net twin for every operator-forced non-carrier location.

    A location the operator named in ``forced_backbone_names`` is fabricated on-net by
    the force pin alone, since any data-center place can become a hub. Carrier PoPs
    named here are already on-net and need no twin. When ``restrict`` is ``True`` a
    forced location whose city is not in ``datacenter_cities`` raises ``ValueError`` --
    the backbone gate is absolute, so a force cannot stand up a hub off a data-center
    city; when ``restrict`` is ``False`` (free-for-all) the gate is lifted and a forced
    location at any city is fabricated. Forced locations are taken in
    a stable id order; co-located sites yield a single twin. The twin always wires to
    its nearest carrier PoPs regardless of distance, so a forced location is dropped
    only in the degenerate case of fewer than :data:`LOCAL_FIBER_MIN_LINKS` carrier
    PoPs at all.
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
            if not is_carrier_pop(vertex) and vertex.name in forced_backbone_names
        ),
        key=lambda vertex: vertex.id,
    ):
        if not backbone_city_allowed(location.info, datacenter_cities, restrict):
            raise ValueError(
                f"forced backbone location is not at a data-center city: {location.name}"
            )
        coord_key = _coord_key(location)
        if coord_key in seen_coords:
            continue
        seen_coords.add(coord_key)
        twin_id = unique_twin_id(f"{ON_NET_ID_PREFIX}{location.id}", used_ids)
        built = build_local_fiber_twin(
            location, twin_id, carrier_pops,
            LocalFiberTwinSpec(note=ON_NET_EDGE_NOTE, shown_in_map=False, max_radius=None),
        )
        if built is None:
            logger.info(
                "Location %s has fewer than %d carrier PoPs to wire to; "
                "leaving it demand-only",
                location.id,
                LOCAL_FIBER_MIN_LINKS,
            )
            continue
        # ``built`` is (twin vertex, its local-fiber edges) -- index in to keep the
        # locals here under pylint's ceiling.
        used_ids.add(twin_id)
        augmented_vertices.append(built[0])
        augmented_edges.update(built[1])
        on_net_ids.add(twin_id)
    return FabricatedOnNetNodes(augmented_vertices, augmented_edges, frozenset(on_net_ids))
