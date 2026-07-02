"""Select and route the backbone-to-backbone mesh.

Every backbone node links to its ``mesh_degree`` nearest reachable backbone nodes,
minus any backbone-backbone pairs the operator pruned in ``etc/*.yml``. The mesh is
then augmented so the backbone is a single connected network and, wherever the carrier
graph allows, 2-vertex-connected -- the physical fiber survives the loss of any single
city, which also implies it survives any single cable cut. These helpers are split from
the synthesizer so the backbone concern stays cohesive and the synthesizer module stays
bounded.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from synthesizer.input_graph import PhysicalEdge, edge_key
from synthesizer.graphs import (
    articulation_points,
    bridges,
    build_adjacency,
    connected_components,
    dijkstra,
    path_edge_keys,
    reconstruct_path,
)
from synthesizer.model import PathUse


def path_geometry_miles(
    path: tuple[str, ...],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> float:
    """Sum the per-span straight-line estimate along a routed path (display)."""
    return sum(
        physical_edges[edge_key(path[index], path[index + 1])].distance_miles
        for index in range(len(path) - 1)
    )


def shortest_link_between(
    left_ids: set[str],
    right_ids: set[str],
    all_distances: dict[str, dict[str, float]],
    blocked: frozenset[tuple[str, str]],
) -> tuple[str, str] | None:
    """The shortest finite, non-blocked pair with one end in each id set, or None.

    ``blocked`` holds the pairs that cannot be used -- operator-pruned links plus the
    links already in the mesh -- so the join never re-adds a pruned pair or a link the
    mesh already has.
    """
    candidates = sorted(
        (all_distances[left].get(right, math.inf), edge_key(left, right))
        for left in left_ids
        for right in right_ids
        if edge_key(left, right) not in blocked
        and math.isfinite(all_distances[left].get(right, math.inf))
    )
    return candidates[0][1] if candidates else None


def augment_for_resilience(
    backbone_ids: tuple[str, ...],
    selected: set[tuple[str, str]],
    all_distances: dict[str, dict[str, float]],
    removed_pairs: frozenset[tuple[str, str]],
) -> set[tuple[str, str]]:
    """Add links so the backbone is one network and survives any single link loss.

    Two passes over the nearest-neighbour mesh, each adding the shortest finite,
    non-pruned link it needs: first stitch any separate clusters into a single
    connected component, then add a parallel link across every remaining bridge so no
    single link is a cut. Each pass stops early if the carrier graph offers no usable
    link (a genuinely unreachable node or a fully pruned join), leaving the mesh as
    connected as it can be rather than blanking it.
    """
    ids = set(backbone_ids)
    edges = set(selected)
    while True:
        components = connected_components(ids, edges)
        if len(components) <= 1:
            break
        head = set(components[0])
        link = shortest_link_between(head, ids - head, all_distances, removed_pairs | edges)
        if link is None:
            break
        edges.add(link)
    while True:
        cut = bridges(ids, edges)
        if not cut:
            break
        side = set(connected_components(ids, edges - {min(cut)})[0])
        link = shortest_link_between(side, ids - side, all_distances, removed_pairs | edges)
        if link is None:
            break
        edges.add(link)
    return edges


def select_backbone_mesh_pairs(
    backbone_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    removed_pairs: frozenset[tuple[str, str]] = frozenset(),
    mesh_degree: int = 3,
) -> list[tuple[str, str]]:
    """Choose which backbone pairs get a logical mesh link.

    Every backbone node links to its ``mesh_degree`` nearest reachable backbone nodes
    (fewer when the backbone itself is smaller), measured over the carrier graph in
    ``all_distances``. Any pair in ``removed_pairs`` -- an operator-pruned
    backbone-backbone link from ``etc/*.yml`` -- is skipped, so the node fills that
    slot with its next nearest peer. The per-node picks are unioned, so a node chosen
    by a farther peer can end with one more link than the target.

    The nearest-neighbour pass alone can leave geographic clusters unlinked -- every
    node's nearest peers sit inside its own cluster -- so the mesh is then augmented
    (see :func:`augment_for_resilience`) into a single connected, 2-edge-connected
    network wherever the carrier graph allows, never re-adding a pruned pair.

    A node left with fewer reachable, non-removed peers than the target -- because the
    operator pruned its links or the carrier graph cannot reach them -- wires to every
    peer it can and no more. Thinning one node below the target therefore costs only
    that node's missing links, never the rest of the backbone, so an operator may
    deliberately isolate a node without blanking the whole mesh.
    """
    target = min(mesh_degree, len(backbone_ids) - 1)
    selected: set[tuple[str, str]] = set()
    for node in backbone_ids:
        distances = all_distances[node]
        nearest = sorted(
            (distances[other], other)
            for other in backbone_ids
            if other != node
            and edge_key(node, other) not in removed_pairs
            and math.isfinite(distances.get(other, math.inf))
        )
        selected.update(edge_key(node, other) for _distance, other in nearest[:target])
    return sorted(augment_for_resilience(backbone_ids, selected, all_distances, removed_pairs))


def _component_index(vertices: set[str], spans: set[tuple[str, str]]) -> dict[str, int]:
    """Map each vertex to the id of the connected piece it lands in."""
    index_of: dict[str, int] = {}
    for index, side in enumerate(connected_components(vertices, spans)):
        for node in side:
            index_of[node] = index
    return index_of


def _separated_backbone_pair(
    cut: str,
    vertices: set[str],
    spans: set[tuple[str, str]],
    backbone_set: set[str],
    removed_pairs: frozenset[tuple[str, str]],
) -> tuple[str, str] | None:
    """A backbone node on each side of a cut city, as a non-pruned edge key.

    Removing the cut city (and every span touching it) splits its component into pieces;
    the backbone nodes the city separates land in different pieces. Returns the cheapest-
    labelled backbone pair sitting in two different pieces whose logical link the operator
    has not pruned, or None when no such pair exists (only transit is separated, or every
    cross pair is pruned). The cut city itself is never an endpoint.
    """
    side_of = _component_index(vertices - {cut}, {span for span in spans if cut not in span})
    backbone_nodes = sorted(node for node in backbone_set if node != cut)
    for offset, near in enumerate(backbone_nodes):
        for far in backbone_nodes[offset + 1:]:
            pair = edge_key(near, far)
            if side_of[near] != side_of[far] and pair not in removed_pairs:
                return pair
    return None


def _resilience_detour(
    spans: set[tuple[str, str]],
    backbone_set: set[str],
    removed_pairs: frozenset[tuple[str, str]],
    adjacency: dict[str, list[tuple[str, float]]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> PathUse | None:
    """One detour route relieving a cut city in the span union, or None when none remains.

    Scans the articulation cities; for the first that separates two backbone nodes, routes
    the cheapest alternate between them that avoids that city -- all of its spans blocked --
    so the city no longer sits on the only path. Returns None when the spans already survive
    any single city loss, or no usable (non-pruned, reachable) alternate exists. Skipping a
    cut that separates only transit is safe: once every backbone-separating cut is relieved,
    the union is biconnected, since each transit city stays joined to a backbone node it
    routes between after any single removal.
    """
    vertices = {vertex for span in spans for vertex in span} | backbone_set
    for cut in sorted(articulation_points(vertices, spans)):
        pair = _separated_backbone_pair(cut, vertices, spans, backbone_set, removed_pairs)
        if pair is None:
            continue
        near, far = pair
        blocked = frozenset(
            edge_key(cut, neighbor) for neighbor, _weight in adjacency.get(cut, [])
        )
        _distances, predecessors = dijkstra(adjacency, near, blocked)
        detour = reconstruct_path(near, far, predecessors)
        if detour:
            return PathUse(
                "backbone_mesh", near, far, detour,
                path_geometry_miles(detour, physical_edges),
            )
    return None


def augment_physical_resilience(
    base_uses: list[PathUse],
    backbone_ids: tuple[str, ...],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    removed_pairs: frozenset[tuple[str, str]],
) -> list[PathUse]:
    """Add detour routes until the backbone's physical spans survive any single city loss.

    The base mesh routes every logical link as an independent shortest path, so a node's
    links share their cheapest egress corridor and one city's loss can sever several. This
    pass takes the union of physical spans the backbone rides and, while any city is a cut
    (an articulation point), routes an alternate around it (see :func:`_resilience_detour`),
    putting that city off the only path. The count of cut cities falls monotonically -- a
    detour merges the two pieces the city separated and adds no new cut, since every city on
    the detour sits on the new cycle -- so it terminates at a biconnected union. It stops
    early when a cut has no usable detour (a genuine carrier chokepoint or a fully pruned
    join); the search gate keeps such sets from winning, and validation reports the truth
    either way.
    """
    adjacency = build_adjacency(physical_edges)
    backbone_set = set(backbone_ids)
    uses = list(base_uses)
    spans: set[tuple[str, str]] = set()
    for use in uses:
        spans |= path_edge_keys(use.path)
    while True:
        detour = _resilience_detour(spans, backbone_set, removed_pairs, adjacency, physical_edges)
        if detour is None:
            break
        uses.append(detour)
        spans |= path_edge_keys(detour.path)
    return uses


@dataclass(frozen=True)
class BackboneConstraints:
    """The backbone-mesh selection knobs: pruned backbone pairs and the link count."""

    removed_pairs: frozenset[tuple[str, str]] = frozenset()
    mesh_degree: int = 3


def backbone_mesh_paths(
    backbone_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    all_predecessors: dict[str, dict[str, str]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    constraints: BackboneConstraints = BackboneConstraints(),
) -> list[PathUse]:
    """Route a shortest path over each backbone-to-backbone mesh link.

    The mesh wires each backbone node to its ``constraints.mesh_degree`` nearest
    nodes, minus ``constraints.removed_pairs`` (see :func:`select_backbone_mesh_pairs`).
    """
    pairs = select_backbone_mesh_pairs(
        backbone_ids, all_distances, constraints.removed_pairs, constraints.mesh_degree
    )
    uses: list[PathUse] = []
    for left, right in pairs:
        path = reconstruct_path(left, right, all_predecessors[left])
        uses.append(
            PathUse("backbone_mesh", left, right, path, path_geometry_miles(path, physical_edges))
        )
    return augment_physical_resilience(
        uses, backbone_ids, physical_edges, constraints.removed_pairs
    )
