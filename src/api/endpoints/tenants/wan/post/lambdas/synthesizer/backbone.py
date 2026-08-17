"""Select and route the backbone-to-backbone mesh.

Every backbone node links to its ``number_of_diverse_paths`` nearest reachable backbone nodes that
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
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from synthesizer.ceiling import (
    BackupRouteLimit,
    RouteGround,
    independent_routes,
    routes_per_peer,
)
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
from synthesizer.model import (
    LINK_FOR_CITY_DETOUR,
    LINK_FOR_CONNECTIVITY,
    LINK_FOR_PIN,
    LINK_FOR_TARGET,
    PathUse,
)

# Slack in miles when a routed length is compared against its budget, absorbing the
# rounding of a sum of great-circle distances. Five millimetres, so it can admit nothing a
# real route could be refused for.
_LIMIT_TOLERANCE = 1e-6


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
    a pin or an earlier pick -- is passed over rather than taken.

    ``slots`` is how many links the node is reaching for: the number of diverse paths its
    tenant asked for, less any the operator already pinned. Diverse candidates fill it
    first, and anything still short is filled from the passed-over ones, nearest first,
    since a link through a chokepoint still beats no link at all.

    The backfill stops at the same number the diverse picks aimed at. A node short of its
    target has a shortfall worth reporting, not a slot worth filling with cable that must
    re-cross a city it already depends on -- and a node that met its target has no slot
    left to fill whatever else its fiber offers.
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
    return picks + passed_over[: max(slots - len(picks), 0)]


def _proven_picks(
    routes: list[tuple[str, ...]],
    nearest: list[tuple[float, str]],
    slots: int,
) -> list[str]:
    """Fill a node's free slots with the peers its own ``routes`` reach.

    The routes were found by proving how many ways out of the node no one city's loss takes
    two of (see :func:`synthesizer.ceiling.independent_routes`), so the peers they end at
    are a set the node can hold independently -- known, not hoped for. Picking them is what
    lets the routing step lay the node's links along the very paths the proof produced. The
    node needs no name here: a route carries its own far end, which is the whole of what a
    pick is.

    Nearer peers are taken first, which is free: the routes are already pairwise clear of
    one another, so order decides only which of them a short reach displaces, never whether
    the ones taken are independent.

    ``nearest`` is the only list of peers this may pick from, which is what keeps a proof
    from overriding the operator. A peer they pruned and a peer they already pinned are both
    absent from it -- the first must not be wired at all, the second is wired already and
    must not take a second slot -- so a proved route to either is passed over here. A ceiling
    counts routes over the fiber and knows nothing of either instruction, so this is the
    place the two are reconciled.

    ``slots`` is how many links the node is reaching for, as in :func:`_diverse_picks`.
    The proof may have found more routes than that -- it counts what the fiber can carry,
    not what anyone asked for -- and the extra ones are left unwired: the number the tenant
    set is the number, and taking a route because it happens to exist is the tool spending
    an operator's cable on its own judgement. Anything still short is filled from the
    nearest peers left over, since a link the proof does not cover still beats no link.
    """
    rank = {peer: index for index, (_distance, peer) in enumerate(nearest)}
    proven = sorted(
        (rank[route[-1]], route[-1]) for route in routes if route[-1] in rank
    )
    picks = [peer for _rank, peer in proven][:slots]
    spare = [peer for _distance, peer in nearest if peer not in picks]
    return picks + spare[: max(slots - len(picks), 0)]


@dataclass(frozen=True)
class BackboneConstraints:
    """The backbone-mesh selection knobs: the operator's pins, prunes, and link count."""

    removed_pairs: frozenset[tuple[str, str]] = frozenset()
    number_of_diverse_paths: int = 3
    forced_pairs: frozenset[tuple[str, str]] = frozenset()
    # the proved diverse routes (see :func:`synthesizer.ceiling.independent_routes`): per
    # node, a set of paths out of it that no one city's loss takes two of -- to distinct
    # peers, or several to the one peer where the backbone holds too few of them. A node
    # present here picks the peers they reach, as many as its target asks for, and is wired
    # along them; an empty mapping means nothing has been proved and peers are picked by
    # distance instead. How many routes there are does not decide how many are taken --
    # that is the tenant's number, and the surplus is left unwired
    routes: Mapping[str, list[tuple[str, ...]]] = field(default_factory=dict)
    # how far a link may be routed against the direct distance between its two ends. It
    # bounds the proof that picks a node's peers (see :func:`backbone_mesh_paths`) and the
    # two heuristics that route everything the proof does not cover, so a node cannot be
    # given a peer it reaches only by a detour nobody would buy. None leaves every route
    # admissible, which is the behaviour of every caller that has no tenant in hand
    limit: BackupRouteLimit | None = None
    # the most backbone seats the tenant's config allows (``backbone.node_count.max`` in
    # its ``etc/`` file). It decides how many routes one pair of sites is drawn with: one,
    # unless the config allows too few seats for the paths asked for, which is a backbone
    # capped at two sites (see :func:`synthesizer.ceiling.routes_per_peer`). None is an
    # operator who capped nothing, and the backbone in hand then says how many peers there
    # are
    seat_cap: int | None = None


@dataclass(frozen=True)
class LinkReason:
    """Why one backbone mesh link is in the design.

    ``requested_by`` names the sites that reached for it, and is empty unless ``reason``
    is :data:`synthesizer.model.LINK_FOR_TARGET`.
    """

    reason: str
    requested_by: tuple[str, ...] = ()


def select_backbone_mesh_pairs(
    backbone_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    constraints: BackboneConstraints = BackboneConstraints(),
) -> dict[tuple[str, str], LinkReason]:
    """Choose which backbone pairs get a logical mesh link, and say why each one is there.

    Every backbone node reaches for exactly ``number_of_diverse_paths`` links -- the number
    of diverse paths its tenant asked for, or one fewer than the backbone itself where the
    backbone is smaller than that. The number is a target and not a floor. Where the fiber
    offers more independently failing routes than were asked for, the surplus is left
    unwired: each link is a real circuit on a real route with a real cost, and an operator
    who asked for two diverse paths has made an engineering decision about how much
    protection this network is worth. Taking more because the ground allows it substitutes
    the tool's judgement for theirs.

    Exceeding the target stays possible, because some of a node's links are not its own
    choice, and the reason each one is there is returned beside it. A node may end above
    its target because the operator pinned a link, because a peer needed this node to reach
    its own target and a link has two ends, because the link holds the backbone together as
    one network, or because it is a detour keeping one city off the only path (that last
    one is added later, when the links are routed -- see
    :func:`augment_physical_resilience`). A link that would exist only because the ground
    was generous is on none of those grounds and is not built.

    Peers are measured over the carrier graph in ``all_distances``. Any pair in
    ``removed_pairs`` -- an operator-pruned backbone-backbone link from ``etc/*.yml`` -- is
    skipped, so the node fills that slot with its next nearest peer. The per-node picks are
    unioned, so a node chosen by a farther peer can end with one more link than it reached
    for itself; that is the second of the four grounds, and the peer that asked is recorded.

    Any pair in ``forced_pairs`` -- an operator-forced backbone-backbone link from
    ``etc/*.yml`` -- is wired however far apart its endpoints are, and counts against
    each endpoint's target: a node with one pin picks only
    ``number_of_diverse_paths - 1`` nearest peers of its own, so the configured number
    keeps meaning what it says and the pin displaces the farthest link the node would
    otherwise have chosen.

    The nearest-neighbour pass alone can leave geographic clusters unlinked -- every
    node's nearest peers sit inside its own cluster -- so the mesh is then augmented
    (see :func:`augment_for_resilience`) into a single connected, 2-edge-connected
    network wherever the carrier graph allows, never re-adding a pruned pair.

    Nearest is not the same as diverse. Where ``constraints.routes`` carries a node's proven
    independent routes, that node's peers are the ones those routes reach (see
    :func:`_proven_picks`): the proof has already found a set of ways out that no one city's
    loss takes two of, so the peers are known to be independently holdable rather than
    guessed at, and the routing step can lay the links along the very paths the proof
    produced. A node absent from the mapping falls back to distance, and an empty mapping is
    the old behaviour exactly.

    That fallback is a heuristic and is documented as one. A candidate whose shortest path
    transits a peer the node has already picked shares that peer's city, so one city's loss
    takes both links and the node's nominal degree overstates what it survives. Such a
    candidate is passed over for the next nearest one that is diverse (see
    :func:`_shares_transit`). Passing over a candidate is not the same as finding a set that
    works, which is why a proof supersedes it wherever one is available.

    A node's pins count as picks either way, so a candidate reachable only through a pinned
    peer is passed over just the same. The pins themselves are wired however they route: an
    operator instruction is honoured, not second-guessed.

    Where no diverse candidate is left, the node falls back to the nearest of the ones
    passed over rather than leaving a slot below its target empty. Some cities are genuine
    carrier chokepoints with no alternate fiber, and a node behind one would otherwise drop
    to a single link; the link is worth having even though it is not independent. Reporting
    that shortfall is validation's job, not selection's.

    A node left with fewer reachable, non-removed peers than its target -- because the
    operator pruned its links or the carrier graph cannot reach them -- wires to every
    peer it can and no more. Thinning one node below its target therefore costs only
    that node's missing links, never the rest of the backbone, so an operator may
    deliberately isolate a node without blanking the whole mesh.

    Nothing here knows which nodes the operator holds to no diverse path count. An
    exemption relieves a node of a requirement and says nothing about how much cable to
    spend on it, so the exemption acts in validation alone and this pass treats every node
    the same.
    """
    forced_pairs = constraints.forced_pairs
    # How many peers a site reaches for, which is its number of diverse paths until the
    # backbone runs out of peers to be one apiece. Past that the paths are not lost, they
    # double up: a site with one peer and two paths asked for wires the one pair here and
    # is drawn with two routes over it (see :func:`_proven_paths_for`). So this bounds the
    # circuits a site opens and not the protection it ends with.
    target = min(constraints.number_of_diverse_paths, len(backbone_ids) - 1)
    requested: dict[tuple[str, str], list[str]] = {}
    for node in backbone_ids:
        for other in _node_picks(node, backbone_ids, all_distances, constraints, target):
            requested.setdefault(edge_key(node, other), []).append(node)
    augmented = augment_for_resilience(
        backbone_ids,
        set(forced_pairs) | set(requested),
        all_distances,
        constraints.removed_pairs,
    )
    return {pair: _link_reason(pair, forced_pairs, requested) for pair in sorted(augmented)}


def _node_picks(
    node: str,
    backbone_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    constraints: BackboneConstraints,
    target: int,
) -> list[str]:
    """The peers ``node`` reaches for: its target, less any the operator already pinned.

    A pruned pair and a pinned pair are both kept out of the candidates it chooses among --
    the first must not be wired at all, the second is wired already and must not take a
    second slot -- and a peer the carrier graph cannot reach goes with them. What is left
    is walked nearest first by :func:`_diverse_picks`, or replaced outright by the proved
    routes where :func:`_proven_picks` has them.
    """
    forced_pairs, removed_pairs = constraints.forced_pairs, constraints.removed_pairs
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
    slots = max(target - len(pinned), 0)
    if node in constraints.routes:
        return _proven_picks(constraints.routes[node], nearest, slots)
    return _diverse_picks(node, nearest, pinned, slots, all_distances)


def _link_reason(
    pair: tuple[str, str],
    forced_pairs: frozenset[tuple[str, str]],
    requested: dict[tuple[str, str], list[str]],
) -> LinkReason:
    """Which of the grounds put ``pair`` in the mesh.

    A pin is checked before a request because a pinned pair is never offered to a node as a
    candidate, so the two cannot both hold. Anything neither pinned nor asked for by an
    endpoint was added to keep the backbone one network (see
    :func:`augment_for_resilience`), which is the only other thing that adds a pair here.
    """
    if pair in forced_pairs:
        return LinkReason(LINK_FOR_PIN)
    if pair in requested:
        return LinkReason(LINK_FOR_TARGET, tuple(sorted(requested[pair])))
    return LinkReason(LINK_FOR_CONNECTIVITY)


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


@dataclass(frozen=True)
class _DetourSubstrate:
    """Everything a detour search reads, which does not change as detours are added.

    The augmentation routes one detour at a time and only the span union moves between
    rounds; the sites in the backbone, the joins the operator pruned, the carrier fiber
    and the backup route limit are the same on every one of them. Bundling them says so,
    and keeps the search's own argument list to the union it is actually iterating on.
    """

    backbone_set: set[str]
    removed_pairs: frozenset[tuple[str, str]]
    adjacency: dict[str, list[tuple[str, float]]]
    physical_edges: dict[tuple[str, str], PhysicalEdge]
    limit: BackupRouteLimit | None = None


def _resilience_detour(
    spans: set[tuple[str, str]],
    ground: _DetourSubstrate,
    blocked_pairs: frozenset[tuple[str, str]],
) -> PathUse | None:
    """One detour route relieving a cut city in the span union, or None when none remains.

    Scans the articulation cities; for the first that separates two backbone nodes, routes
    the shortest alternate between them that avoids that city -- all of its spans blocked --
    so the city no longer sits on the only path. Returns None when the spans already survive
    any single city loss, or no usable (non-pruned, reachable) alternate exists. Skipping a
    cut that separates only transit is safe: once every backbone-separating cut is relieved,
    the union is biconnected, since each transit city stays joined to a backbone node it
    routes between after any single removal.

    ``blocked_pairs`` are the pairs this pass may not draw another route between: the ones
    the operator pruned, and the ones already holding every route their tenant asked for. A
    cut whose only separated pair is blocked is left alone rather than relieved, so the pass
    can end with a city still on the only path. That is the honest report -- the fiber here
    cannot survive that city's loss inside the number of paths the operator bought -- and
    validation is what says so.
    """
    vertices = {vertex for span in spans for vertex in span} | ground.backbone_set
    for cut in sorted(articulation_points(vertices, spans)):
        pair = _separated_backbone_pair(
            cut, vertices, spans, ground.backbone_set, blocked_pairs
        )
        if pair is None:
            continue
        near, far = pair
        blocked = frozenset(
            edge_key(cut, neighbor) for neighbor, _weight in ground.adjacency.get(cut, [])
        )
        _distances, predecessors = dijkstra(ground.adjacency, near, blocked)
        detour = reconstruct_path(near, far, predecessors)
        miles = path_geometry_miles(detour, ground.physical_edges) if detour else 0.0
        if within_limit(detour, near, far, miles, ground.limit):
            return PathUse(
                "backbone_mesh", near, far, detour, miles, LINK_FOR_CITY_DETOUR,
            )
    return None


def _pairs_at_their_limit(
    uses: list[PathUse], routes_per_pair: int
) -> frozenset[tuple[str, str]]:
    """The backbone pairs already carrying every route their tenant allows the pair."""
    drawn: dict[tuple[str, str], int] = {}
    for use in uses:
        pair = edge_key(use.source, use.target)
        drawn[pair] = drawn.get(pair, 0) + 1
    return frozenset(
        pair for pair, count in drawn.items() if count >= routes_per_pair
    )


def augment_physical_resilience(
    base_uses: list[PathUse],
    backbone_ids: tuple[str, ...],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    constraints: BackboneConstraints = BackboneConstraints(),
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

    ``constraints.limit`` makes a detour past the operator's backup route multiple one of
    the unusable ones. A city stays a cut rather than being relieved by a route nobody would
    build, which is the
    honest report: the fiber here cannot survive that city's loss, and saying so is worth
    more than a cable on the map that would never be ordered.

    The routes one pair is allowed stop the pass drawing it any more than that (see
    :func:`synthesizer.ceiling.routes_per_peer`), which is one route wherever there are peers
    enough to reach instead. Each round relieves one city and rides the same fiber for the
    rest of the way, so a corridor with several chokepoints takes one route per chokepoint if
    nothing holds the pass back -- Ashburn, VA to Salt Lake City, UT crosses eight and took
    four extra routes and 5,633 miles of haul for them (GitHub issue #58). A pair holding the
    routes it is allowed is protected by them, and a chokepoint they leave standing is a
    shortfall to report rather than a reason to buy another circuit.

    The pass still has somewhere to go when every drawn pair is at its limit: a pair of
    sites the cut city separates that is not joined at all holds no route yet, so relieving
    the city by joining two sites that were not neighbours is the repair left to it.
    """
    removed_pairs = constraints.removed_pairs
    per_pair = routes_per_peer(
        constraints.seat_cap, len(backbone_ids), constraints.number_of_diverse_paths
    )
    ground = _DetourSubstrate(
        set(backbone_ids), removed_pairs, build_adjacency(physical_edges),
        physical_edges, constraints.limit,
    )
    uses = list(base_uses)
    spans: set[tuple[str, str]] = set()
    for use in uses:
        spans |= path_edge_keys(use.path)
    while True:
        blocked = removed_pairs | _pairs_at_their_limit(uses, per_pair)
        detour = _resilience_detour(spans, ground, blocked)
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


def _route_miles(
    route: tuple[str, ...], adjacency: dict[str, list[tuple[str, float]]]
) -> float:
    """The distance a route covers over the carrier graph."""
    hops = zip(route, route[1:])
    return sum(
        next(weight for neighbor, weight in adjacency[city] if neighbor == nxt)
        for city, nxt in hops
    )


def within_limit(
    route: tuple[str, ...],
    left: str,
    right: str,
    miles: float,
    limit: BackupRouteLimit | None,
) -> bool:
    """Whether a routed ``left``-to-``right`` link is inside the operator's backup route
    multiple.

    An empty route is never inside it, since there is no route to be inside anything. With
    no limit every route passes, which is the behaviour of every caller with no tenant in
    hand.

    A pair the substrate cannot join at all has no direct distance to measure against, so
    nothing is asserted about it: the bound says a protect path may not run far past the
    working path, and where there is no working path the bound has no opinion rather than a
    silent refusal.
    """
    if not route:
        return False
    if limit is None:
        return True
    direct = limit.distances.get(left, {}).get(right, math.inf)
    if not math.isfinite(direct):
        return True
    return miles <= limit.multiple * direct + _LIMIT_TOLERANCE


def _clearest_route(
    left: str,
    right: str,
    carried: dict[str, set[str]],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: BackupRouteLimit | None = None,
) -> tuple[str, ...]:
    """The route clearing as many of the endpoints' carried cities as the fiber allows.

    Clearing both endpoints' cities is what the link is worth most, so it is tried first.
    Where the fiber has no such route, clearing one endpoint's cities is still worth
    having: independence is counted per node, so a route that shares a city with the far
    end's other links costs this end nothing, and one of the two nodes keeps a link that
    fails on its own. The cheaper of the two one-sided routes wins, and an endpoint
    carrying nothing yet is not tried again under its own name -- its set is the whole
    set, which has just failed.

    Returns empty when the fiber offers no route clear of either end's cities. Falling
    back to the shortest path is the caller's business, since it is the caller that knows
    a link must be routed somehow.

    ``limit`` bounds how far a clearing route may run against the direct distance between
    the two ends, and a route past it is discarded rather than taken. Independence bought
    that way is not worth having: the route exists to carry the traffic when the other one
    fails, and one four hundred times as long does not do that. A link whose only clear
    route is over the bound falls back to its shortest path and reads as the shortfall it
    is, which validation reports.
    """
    left_cities = carried.get(left, set()) - {left, right}
    right_cities = carried.get(right, set()) - {left, right}
    both = left_cities | right_cities
    if not both:
        return ()

    def admissible(route: tuple[str, ...]) -> bool:
        """Whether this clearing route is one the operator's bound allows."""
        return within_limit(route, left, right, _route_miles(route, adjacency), limit)

    route = _route_avoiding(left, right, both, adjacency)
    if admissible(route):
        return route
    one_sided = [
        _route_avoiding(left, right, cities, adjacency)
        for cities in (left_cities, right_cities)
        if cities and cities != both
    ]
    clear = [route for route in one_sided if admissible(route)]
    if not clear:
        return ()
    return min(clear, key=lambda route: (_route_miles(route, adjacency), route))


def _proven_paths_for(
    left: str,
    right: str,
    proven: Mapping[str, list[tuple[str, ...]]],
    adjacency: dict[str, list[tuple[str, float]]],
    count: int,
) -> list[tuple[str, ...]]:
    """The proved paths between ``left`` and ``right``, oriented from ``left``, or empty.

    Each endpoint may have proved its own way to the other, and the two need not agree,
    because each proof is the cheapest set of routes out of *its own* site and the two sites
    have different other peers to keep clear of.

    A path and its reverse are the same fiber, so they collapse to one.

    ``count`` is how many routes this pair is allowed and no more than that many come back,
    fewest miles first. It is one wherever there are peers enough for a site to answer its
    number by reaching different ones, which is every tenant but one whose config caps the
    backbone at two sites (see :func:`synthesizer.ceiling.routes_per_peer`). A pair joined
    twice is a second circuit somebody orders every month for two sites that are already
    joined, and the money buys nothing the far end of either route can use: what makes a
    site's ways out independent is that they end at different peers.

    So where the two ends disagree the shorter route is drawn and the longer is not. That
    can leave the site whose route was dropped riding one city for two of its links, and the
    honest answer to that is the shortfall ``synthesizer.validation`` reports and the detour
    :func:`augment_physical_resilience` draws between two sites not yet joined -- not a
    second circuit between two that already are (GitHub issue #59).
    """
    found: list[tuple[str, ...]] = []
    for near, far in ((left, right), (right, left)):
        for route in proven.get(near, ()):
            if route[-1] != far:
                continue
            forward = route if near == left else tuple(reversed(route))
            if forward not in found:
                found.append(forward)
    return sorted(found, key=lambda route: (_route_miles(route, adjacency), route))[:count]


def diverse_mesh_routes(
    pairs: list[tuple[str, str]],
    backbone_ids: tuple[str, ...],
    all_predecessors: dict[str, dict[str, str]],
    adjacency: dict[str, list[tuple[str, float]]],
    constraints: BackboneConstraints = BackboneConstraints(),
) -> list[tuple[str, str, tuple[str, ...]]]:
    """Route every mesh link, keeping one node's links clear of each other's cities.

    Where ``constraints.routes`` carries a node's independent routes (see
    :func:`synthesizer.ceiling.independent_routes`), a link that pair is wired along the
    path the proof found for it. That is the whole of what makes a node reach the degree its
    fiber allows: those paths are pairwise clear of one another by construction, so a node
    whose links are laid along them holds as many independently failing links as the proof
    says it can, and no ordering of the pairs and no later measurement is involved. The
    number of links and the paths they take come from the same calculation, so neither can
    be right while the other is wrong.

    Every other link is routed by the heuristic below, which is what the fiber leaves to
    judgement: an operator's pin, a join added to hold the backbone together, a slot filled
    to the tenant's floor. Routing each of those along its own shortest path independently
    would let a node's links share their cheapest egress corridor, so one city's loss takes
    several at once. Each is therefore routed clear of the cities its endpoints' other links
    already ride, proved ones included, accepting a longer path to buy the independence.

    Clearing both ends at once is not always possible, and where it is not the link still
    clears one of them (see :func:`_clearest_route`): independence is counted per node, so
    a route that gives up on the far end's cities still buys this end a link that fails on
    its own. Only when neither end can be cleared is the shortest path taken.

    The endpoints themselves are never avoided, since a link cannot route around its own
    ends. A link with no clear route falls back to its shortest path: the fiber genuinely
    offers no alternative there, and validation is what reports the shortfall.

    ``constraints.limit`` bounds the heuristic's clearing routes (see
    :func:`_clearest_route`), and a link whose only clear route runs past it falls back the
    same way one with no clear route at all does. The proved paths need no such check here:
    the proof is already bounded where it is computed, so a route reaching this function has
    passed the same test over the same fiber.

    How many routes one pair is drawn with is decided here (see :func:`_proven_paths_for`),
    and it is one unless there are too few peers for a site to answer its number over
    distinct ones -- which ``backbone_ids`` and ``constraints.seat_cap`` between them say
    (see :func:`synthesizer.ceiling.routes_per_peer`). The proof counts what the fiber can
    carry, which between one pair of sites can be several routes, and this is where how many
    of them are built is decided.
    """
    carried: dict[str, set[str]] = {}
    routes: list[tuple[str, str, tuple[str, ...]]] = []

    def lay(left: str, right: str, path: tuple[str, ...]) -> None:
        """Record one routed link and charge its cities to both of its endpoints."""
        routes.append((left, right, path))
        for node in (left, right):
            carried.setdefault(node, set()).update(set(path) - {node})

    per_pair = routes_per_peer(
        constraints.seat_cap, len(backbone_ids), constraints.number_of_diverse_paths
    )
    unproved: list[tuple[str, str]] = []
    for left, right in pairs:
        paths = _proven_paths_for(left, right, constraints.routes, adjacency, per_pair)
        if not paths:
            unproved.append((left, right))
        for path in paths:
            lay(left, right, path)
    for left, right in unproved:
        path = _clearest_route(left, right, carried, adjacency, constraints.limit)
        if not path:
            path = reconstruct_path(left, right, all_predecessors[left])
        lay(left, right, path)
    return routes


def backbone_mesh_paths(
    backbone_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    all_predecessors: dict[str, dict[str, str]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    constraints: BackboneConstraints = BackboneConstraints(),
) -> list[PathUse]:
    """Route each backbone-to-backbone mesh link, diversely where the fiber allows.

    The mesh wires each backbone node to its nearest nodes, plus
    ``constraints.forced_pairs`` and minus ``constraints.removed_pairs`` (see
    :func:`select_backbone_mesh_pairs`). Routing is not per-link shortest path: a node's
    links are routed clear of one another's cities so the degree counts links that fail
    independently (see :func:`diverse_mesh_routes`).

    Which peers each node reaches for is proved here rather than asked of the caller: the
    routes come off the same substrate ``physical_edges`` describes (see
    :func:`synthesizer.ceiling.independent_routes`), so the peers a node is wired to and
    the paths its links are laid along cannot disagree. Any routes already on
    ``constraints`` are replaced for that reason.

    The proof says which peers a node *could* hold independently, and the tenant's number
    says how many of them it takes. The two are deliberately separate: a proof that finds
    ten ways out of a city is a fact about the fiber, not an instruction to buy ten
    circuits.

    ``constraints.limit`` bounds how far the proof may route (see
    :func:`synthesizer.ceiling.independent_routes`). The proof is the reason it must be
    applied here rather than to the drawn links afterwards: these routes are laid verbatim,
    so a route the proof finds is cable the design orders. The proof prices its own routes
    by mileage and still needs the bound, because it maximises how many routes it finds
    before it minimises what they cost: where an ocean crossing is the only way to one more
    peer it is taken to protect a link across a state line, and the bound is what refuses
    it.
    """
    adjacency = build_adjacency(physical_edges)
    ground = RouteGround(
        backbone_ids, adjacency, constraints.limit,
        constraints.number_of_diverse_paths, constraints.seat_cap,
    )
    proven = {
        node: independent_routes(node, ground)
        for node in backbone_ids
        if node in adjacency
    }
    constraints = replace(constraints, routes=proven)
    reasons = select_backbone_mesh_pairs(backbone_ids, all_distances, constraints)
    uses = [
        PathUse(
            "backbone_mesh", left, right, path,
            path_geometry_miles(path, physical_edges),
            reasons[edge_key(left, right)].reason,
            reasons[edge_key(left, right)].requested_by,
        )
        for left, right, path in diverse_mesh_routes(
            sorted(reasons), backbone_ids, all_predecessors, adjacency, constraints
        )
    ]
    return augment_physical_resilience(
        uses, backbone_ids, physical_edges, constraints
    )
