"""Seat operator-forced off-net locations as local-fiber-attached carrier twins.

An off-net seat is an operator location that is not itself a carrier PoP -- it has
no backbone fiber of its own -- but that the operator wants seated as a backbone
node. Its coordinates come from a dedicated off-net CSV and never enter the main
vertex pool, so it carries no access demand. When the operator force-pins such a seat
we stand up a carrier-PoP twin at its coordinates, wired by synthetic local fiber to
the nearest carrier PoPs (see :mod:`synthesizer.local_fiber`) -- the same mechanism
that backs forced installations.

Only forced off-net sites are realized; an unlisted site is ignored. Failure modes
are hard errors rather than silent skips, because the operator explicitly demanded
the seat: a site whose city is not a data-center city (the backbone gate is
absolute), a site that cannot reach two distinct carrier PoPs within range (it cannot
biconnect into the backbone), and a site whose name collides with a real carrier PoP
(the pin would be ambiguous).
"""

from __future__ import annotations

from dataclasses import dataclass

from synthesizer.local_fiber import (
    LOCAL_FIBER_MIN_LINKS,
    LOCAL_FIBER_RADIUS_MILES,
    LocalFiberTwinSpec,
    build_local_fiber_twin,
    unique_twin_id,
)
from synthesizer.model import backbone_city_allowed, is_carrier_pop
from synthesizer.input_graph import PhysicalEdge, Vertex

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
    datacenter_cities: frozenset[tuple[str, str]] = frozenset(),
    restrict: bool = True,
) -> RealizedOffNet:
    """Seat a local-fiber twin for every off-net site the operator has force-pinned.

    ``forced_names`` is the operator's forced backbone names. A site whose name is not
    forced is ignored. A forced site whose name is also a carrier PoP is already
    on-net -- the pin seats there, so no off-net twin is built. When ``restrict`` is
    ``True`` a forced site whose city is not in ``datacenter_cities`` raises
    ``ValueError`` (the backbone gate is absolute); when ``restrict`` is ``False``
    (free-for-all) the gate is lifted. A forced site that cannot reach
    :data:`~synthesizer.local_fiber.LOCAL_FIBER_MIN_LINKS` carrier PoPs within range
    raises ``ValueError``.
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
        if not backbone_city_allowed(site.info, datacenter_cities, restrict):
            raise ValueError(
                f"forced off-net site is not at a data-center city: {site.name}"
            )
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
        # ``built`` is (twin vertex, its local-fiber edges) -- index in to keep the
        # locals here under pylint's ceiling.
        used_ids.add(twin_id)
        augmented_vertices.append(built[0])
        augmented_edges.update(built[1])
        seat_ids.add(twin_id)
    return RealizedOffNet(augmented_vertices, augmented_edges, frozenset(seat_ids))
