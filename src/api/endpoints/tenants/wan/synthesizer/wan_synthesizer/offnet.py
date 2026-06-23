"""Seat operator-forced off-net locations as local-fiber-attached carrier twins.

An off-net seat is an operator location that is not itself a carrier PoP -- it has
no backbone fiber of its own -- but that the operator wants seated as a core and/or
an aggregation. Its coordinates come from a dedicated off-net CSV and never enter
the main vertex pool, so it carries no access demand. When the operator force-pins
such a seat we stand up a carrier-PoP twin at its coordinates, wired by synthetic
local fiber to the nearest carrier PoPs (see :mod:`wan_synthesizer.local_fiber`) -- the
same mechanism that backs forced installations, except an off-net seat may be a
core as well as an aggregation.

Only forced off-net sites are realized; an unlisted site is ignored. Two failure
modes are hard errors rather than silent skips, because the operator explicitly
demanded the seat: a site that cannot reach two distinct carrier PoPs within range
(it cannot biconnect into the backbone), and a site whose name collides with a real
carrier PoP (the pin would be ambiguous).
"""

from __future__ import annotations

from dataclasses import dataclass

from wan_synthesizer.local_fiber import (
    LOCAL_FIBER_MIN_LINKS,
    LOCAL_FIBER_RADIUS_MILES,
    LocalFiberTwinSpec,
    build_local_fiber_twin,
    unique_twin_id,
)
from wan_synthesizer.model import is_carrier_pop
from wan_graph.model import PhysicalEdge, Vertex

OFF_NET_ID_PREFIX = "offnet_"
OFF_NET_EDGE_NOTE = "synthetic off-net local-fiber link"


@dataclass(frozen=True)
class RealizedOffNet:
    """Off-net seats realized into the graph as local-fiber-attached carrier twins.

    ``vertices`` and ``physical_edges`` are the graph augmented with one twin PoP per
    forced off-net seat and its synthetic local-fiber links; ``seat_ids`` are those
    twins' ids. Each twin is resolved onto the operator's force-pin downstream.
    """

    vertices: list[Vertex]
    physical_edges: dict[tuple[str, str], PhysicalEdge]
    seat_ids: frozenset[str]


def realize_off_net_sites(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    sites: list[Vertex],
    forced_names: frozenset[str],
) -> RealizedOffNet:
    """Seat a local-fiber twin for every off-net site the operator has force-pinned.

    ``forced_names`` is the union of the operator's forced core and aggregation names.
    A site whose name is not forced is ignored. A forced site whose name is also a
    carrier PoP is already on-net -- the pin seats there, so no off-net twin is built.
    A forced site that cannot reach :data:`~wan_synthesizer.local_fiber.LOCAL_FIBER_MIN_LINKS`
    carrier PoPs within range raises ``ValueError``.
    """
    carrier_pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    carrier_names = {pop.name for pop in carrier_pops}
    used_ids = {vertex.id for vertex in vertices}
    augmented_vertices = list(vertices)
    augmented_edges = dict(physical_edges)
    seat_ids: set[str] = set()
    for site in sorted(sites, key=lambda vertex: vertex.id):
        if site.name not in forced_names:
            continue
        if site.name in carrier_names:
            # Already an on-net carrier PoP; the forced pin seats there, no twin needed.
            continue
        twin_id = unique_twin_id(f"{OFF_NET_ID_PREFIX}{site.id}", used_ids)
        built = build_local_fiber_twin(
            site, twin_id, carrier_pops,
            LocalFiberTwinSpec(note=OFF_NET_EDGE_NOTE, shown_in_map=True),
        )
        if built is None:
            raise ValueError(
                f"off-net site {site.name} has fewer than {LOCAL_FIBER_MIN_LINKS} "
                f"carrier PoPs within {LOCAL_FIBER_RADIUS_MILES:.0f} mi; cannot seat it"
            )
        twin, edges = built
        used_ids.add(twin_id)
        augmented_vertices.append(twin)
        augmented_edges.update(edges)
        seat_ids.add(twin_id)
    return RealizedOffNet(augmented_vertices, augmented_edges, frozenset(seat_ids))
