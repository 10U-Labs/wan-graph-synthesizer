"""Select and route the backbone-to-backbone mesh.

Every backbone node links to its ``mesh_degree`` nearest reachable backbone nodes that
do not route through one another, minus any backbone-backbone pairs the operator pruned
in ``etc/*.yml``. Counting links that share a transit city would let a node report its
full degree and still fall to one link when that city goes. The mesh is then augmented
so the backbone is a single connected network and, wherever the carrier graph allows,
2-vertex-connected -- the physical fiber survives the loss of any single
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


def _shares_transit(
    node: str,
    candidate: str,
    chosen: set[str],
    all_distances: dict[str, dict[str, float]],
) -> bool:
    """Whether the shortest path to ``candidate`` runs through a peer already chosen.

    A peer sits on a shortest ``node``-to-``candidate`` path exactly when the two legs
    sum to the direct distance, since every subpath of a shortest path is itself
    shortest. Such a candidate buys no redundancy: one city's loss takes both links at
    once. Where the graph offers two equally short routes and only one of them transits
    the peer, this still reports a share -- the router is free to pick either, so the
    diversity cannot be relied on.
    """
    direct = all_distances[node].get(candidate, math.inf)
    return any(
        math.isclose(
            all_distances[node].get(peer, math.inf)
            + all_distances.get(peer, {}).get(candidate, math.inf),
            direct,
            rel_tol=1e-9,
        )
        for peer in chosen
    )


def _diverse_picks(
    node: str,
    nearest: list[tuple[float, str]],
    pinned: set[str],
    slots: int,
    all_distances: dict[str, dict[str, float]],
) -> list[str]:
    """Fill ``node``'s free slots from ``nearest``, preferring peers it shares no transit with.

    Candidates are walked nearest first; one that routes through a peer already held --
    a pin or an earlier pick -- is passed over rather than taken. Slots left over once
    the diverse candidates run out are filled from the passed-over ones, nearest first,
    since a link through a chokepoint still beats no link at all.
    """
    chosen = set(pinned)
    picks: list[str] = []
    passed_over: list[str] = []
    for _distance, other in nearest:
        if len(picks) == slots:
            break
        if _shares_transit(node, other, chosen, all_distances):
            passed_over.append(other)
            continue
        picks.append(other)
        chosen.add(other)
    return picks + passed_over[: slots - len(picks)]


def select_backbone_mesh_pairs(
    backbone_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    removed_pairs: frozenset[tuple[str, str]] = frozenset(),
    mesh_degree: int = 3,
    forced_pairs: frozenset[tuple[str, str]] = frozenset(),
    degree_exempt: frozenset[str] = frozenset(),
) -> list[tuple[str, str]]:
    """Choose which backbone pairs get a logical mesh link.

    Every backbone node links to its ``mesh_degree`` nearest reachable backbone nodes
    (fewer when the backbone itself is smaller), measured over the carrier graph in
    ``all_distances``. Any pair in ``removed_pairs`` -- an operator-pruned
    backbone-backbone link from ``etc/*.yml`` -- is skipped, so the node fills that
    slot with its next nearest peer. The per-node picks are unioned, so a node chosen
    by a farther peer can end with one more link than the target.

    Any pair in ``forced_pairs`` -- an operator-forced backbone-backbone link from
    ``etc/*.yml`` -- is wired however far apart its endpoints are, and counts against
    each endpoint's degree: a node with one pin picks only ``mesh_degree - 1`` nearest
    peers of its own, so the configured degree keeps meaning what it says and the pin
    displaces the farthest link the node would otherwise have chosen.

    The nearest-neighbour pass alone can leave geographic clusters unlinked -- every
    node's nearest peers sit inside its own cluster -- so the mesh is then augmented
    (see :func:`augment_for_resilience`) into a single connected, 2-edge-connected
    network wherever the carrier graph allows, never re-adding a pruned pair.

    Nearest is not the same as diverse. A candidate whose shortest path transits a peer
    the node has already picked shares that peer's city, so one city's loss takes both
    links and the node's nominal degree overstates what it survives. Such a candidate is
    passed over for the next nearest one that is diverse (see :func:`_shares_transit`),
    which is what makes the degree a count of independent links rather than of lines on
    a diagram. A node's pins count as picks here too, so a candidate reachable only
    through a pinned peer is passed over just the same. The pins themselves are wired
    however they route: an operator instruction is honoured, not second-guessed.

    Where no diverse candidate is left, the node falls back to the nearest of the ones
    passed over rather than leaving the slot empty. Some cities are genuine carrier
    chokepoints with no alternate fiber, and a node behind one would otherwise drop to a
    single link; the link is worth having even though it is not independent. Reporting
    that shortfall is validation's job, not selection's.

    A node left with fewer reachable, non-removed peers than the target -- because the
    operator pruned its links or the carrier graph cannot reach them -- wires to every
    peer it can and no more. Thinning one node below the target therefore costs only
    that node's missing links, never the rest of the backbone, so an operator may
    deliberately isolate a node without blanking the whole mesh.

    A node in ``degree_exempt`` picks no peers of its own: the operator has said the
    degree is not asked of it, and filling slots at a spur only spends links on a target
    it was never going to make. It keeps whatever the operator pinned onto it, stays a
    peer any other node may pick, and is still wired in by the resilience augmentation,
    so exempting a node thins it rather than cutting it out of the mesh.
    """
    target = min(mesh_degree, len(backbone_ids) - 1)
    selected: set[tuple[str, str]] = set(forced_pairs)
    for node in backbone_ids:
        if node in degree_exempt:
            continue
        distances = all_distances[node]
        nearest = sorted(
            (distances[other], other)
            for other in backbone_ids
            if other != node
            and edge_key(node, other) not in removed_pairs
            and edge_key(node, other) not in forced_pairs
            and math.isfinite(distances.get(other, math.inf))
        )
        pinned = {peer for pair in forced_pairs if node in pair for peer in pair if peer != node}
        picks = _diverse_picks(
            node, nearest, pinned, max(target - len(pinned), 0), all_distances
        )
        selected.update(edge_key(node, other) for other in picks)
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


def _route_avoiding(
    left: str,
    right: str,
    avoid: set[str],
    adjacency: dict[str, list[tuple[str, float]]],
) -> tuple[str, ...]:
    """The shortest ``left``-to-``right`` route clear of ``avoid``, or empty when none is.

    A city is kept off the route by blocking every span that touches it, the same way
    :func:`_resilience_detour` puts a cut city off the only path.
    """
    blocked = frozenset(
        edge_key(city, neighbor)
        for city in avoid
        for neighbor, _weight in adjacency.get(city, [])
    )
    _distances, predecessors = dijkstra(adjacency, left, blocked)
    return reconstruct_path(left, right, predecessors)


def diverse_mesh_routes(
    pairs: list[tuple[str, str]],
    all_predecessors: dict[str, dict[str, str]],
    adjacency: dict[str, list[tuple[str, float]]],
) -> list[tuple[str, str, tuple[str, ...]]]:
    """Route every mesh link, keeping one node's links clear of each other's cities.

    Routing each link along its own shortest path independently lets a node's links share
    their cheapest egress corridor, so one city's loss takes several at once and the
    node's degree overstates what it survives. Each link is therefore routed clear of the
    cities its endpoints' earlier links already ride, accepting a longer path to buy the
    independence -- selection can only choose which peers a node links to, and no choice
    of peer helps when the shortest routes to all of them leave through one city.

    The endpoints themselves are never avoided, since a link cannot route around its own
    ends. A link with no clear route falls back to its shortest path: the fiber genuinely
    offers no alternative there, and validation is what reports the shortfall.
    """
    carried: dict[str, set[str]] = {}
    routes: list[tuple[str, str, tuple[str, ...]]] = []
    for left, right in pairs:
        avoid = (carried.get(left, set()) | carried.get(right, set())) - {left, right}
        path = _route_avoiding(left, right, avoid, adjacency) if avoid else ()
        if not path:
            path = reconstruct_path(left, right, all_predecessors[left])
        routes.append((left, right, path))
        for node in (left, right):
            carried.setdefault(node, set()).update(set(path) - {node})
    return routes


@dataclass(frozen=True)
class BackboneConstraints:
    """The backbone-mesh selection knobs: the operator's pins, prunes, and link count."""

    removed_pairs: frozenset[tuple[str, str]] = frozenset()
    mesh_degree: int = 3
    forced_pairs: frozenset[tuple[str, str]] = frozenset()
    degree_exempt: frozenset[str] = frozenset()  # nodes the degree is not asked of


def backbone_mesh_paths(
    backbone_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    all_predecessors: dict[str, dict[str, str]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    constraints: BackboneConstraints = BackboneConstraints(),
) -> list[PathUse]:
    """Route each backbone-to-backbone mesh link, diversely where the fiber allows.

    The mesh wires each backbone node to its ``constraints.mesh_degree`` nearest nodes,
    plus ``constraints.forced_pairs`` and minus ``constraints.removed_pairs`` (see
    :func:`select_backbone_mesh_pairs`), and asks the degree of nobody in
    ``constraints.degree_exempt``. Routing is not per-link shortest path: a node's
    links are routed clear of one another's cities so the degree counts links that fail
    independently (see :func:`diverse_mesh_routes`).
    """
    pairs = select_backbone_mesh_pairs(
        backbone_ids,
        all_distances,
        constraints.removed_pairs,
        constraints.mesh_degree,
        constraints.forced_pairs,
        constraints.degree_exempt,
    )
    adjacency = build_adjacency(physical_edges)
    uses = [
        PathUse("backbone_mesh", left, right, path, path_geometry_miles(path, physical_edges))
        for left, right, path in diverse_mesh_routes(pairs, all_predecessors, adjacency)
    ]
    return augment_physical_resilience(
        uses, backbone_ids, physical_edges, constraints.removed_pairs
    )
