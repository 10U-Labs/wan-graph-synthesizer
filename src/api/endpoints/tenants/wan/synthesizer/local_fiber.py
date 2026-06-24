"""Attach a non-PoP site to the backbone via synthetic local-fiber links.

A site that carries no fiber of its own (a forced installation, an off-net
operator seat) can still be seated on the carrier backbone by standing up a
co-located carrier-PoP *twin* at its coordinates and wiring that twin to the
nearest existing carrier PoPs with synthetic local-fiber edges. The twin's name
matches the site, so an operator force-pin resolves onto it and the rest of the
synthesizer is none the wiser. A site without at least :data:`LOCAL_FIBER_MIN_LINKS`
carrier PoPs within :data:`LOCAL_FIBER_RADIUS_MILES` cannot be biconnected into the
backbone, so the twin is not built (the caller decides whether that is a skip or an
error). This module is the single home of that primitive, shared by the
installation and off-net seating layers.
"""

from __future__ import annotations

from dataclasses import dataclass

from synthesizer.input_graph import (
    PhysicalEdge,
    Vertex,
    edge_key,
    haversine_miles,
)
from synthesizer.model import KIND_POP

LOCAL_FIBER_LINKS = 3
LOCAL_FIBER_MIN_LINKS = 2
LOCAL_FIBER_RADIUS_MILES = 300.0


@dataclass(frozen=True)
class LocalFiberTwinSpec:
    """How to seat a local-fiber twin: edge note, map visibility, and reach cap.

    ``max_radius`` of ``None`` removes the distance cap so an operator-forced site is
    always seated, wired to its nearest carrier PoPs regardless of distance.
    """

    note: str
    shown_in_map: bool
    max_radius: float | None = LOCAL_FIBER_RADIUS_MILES


def nearest_carrier_pops(
    vertex: Vertex, carrier_pops: list[Vertex], links: int, max_radius: float | None
) -> list[Vertex]:
    """The up-to-``links`` nearest carrier PoPs, capped at ``max_radius`` if given.

    ``max_radius`` of ``None`` removes the distance cap: the nearest ``links`` PoPs
    are returned regardless of distance. This honours an operator force even where our
    public data records no nearby fiber -- fiber exists everywhere, we just lack it.
    """
    ranked = sorted(
        ((haversine_miles(vertex, pop), pop) for pop in carrier_pops),
        key=lambda item: (item[0], item[1].id),
    )
    return [
        pop
        for distance, pop in ranked[:links]
        if max_radius is None or distance <= max_radius
    ]


def unique_twin_id(base: str, used_ids: set[str]) -> str:
    """A twin id derived from ``base`` that no existing vertex already uses."""
    vertex_id = base
    suffix = 2
    while vertex_id in used_ids:
        vertex_id = f"{base}_{suffix}"
        suffix += 1
    return vertex_id


def build_local_fiber_twin(
    site: Vertex,
    twin_id: str,
    carrier_pops: list[Vertex],
    spec: LocalFiberTwinSpec,
) -> tuple[Vertex, dict[tuple[str, str], PhysicalEdge]] | None:
    """A co-located carrier-PoP twin for ``site`` plus its local-fiber edges.

    Returns the ``KIND_POP`` twin and its synthetic links to the nearest carrier
    PoPs, or ``None`` only when fewer than :data:`LOCAL_FIBER_MIN_LINKS` carrier PoPs
    are available to wire to (``spec.max_radius`` of ``None`` lifts the distance cap).
    """
    neighbors = nearest_carrier_pops(
        site, carrier_pops, LOCAL_FIBER_LINKS, spec.max_radius
    )
    if len(neighbors) < LOCAL_FIBER_MIN_LINKS:
        return None
    twin = Vertex(
        id=twin_id,
        name=site.name,
        kind=KIND_POP,
        coords=site.coords,
        info=site.info,
        shown_in_map=spec.shown_in_map,
    )
    edges: dict[tuple[str, str], PhysicalEdge] = {}
    for pop in neighbors:
        key = edge_key(twin.id, pop.id)
        edges[key] = PhysicalEdge(
            source=key[0],
            target=key[1],
            distance_miles=haversine_miles(twin, pop),
            note=spec.note,
        )
    return twin, edges
