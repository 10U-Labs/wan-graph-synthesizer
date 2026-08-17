"""How many independently failing links a backbone node's fiber can actually carry.

The number of diverse paths asks for links that fail independently: two links leaving a node through
one city are one link the moment that city goes. So the question "how many links should
this node have" is really "how many routes out of it reach the rest of the backbone
without sharing a city", and that is a fact about the substrate rather than a number
anyone chooses. This module computes it, once per backbone node, and calls it the node's
ceiling.

The routes behind the number are worth as much as the number. A count says a node is
short; the routes say what it is short of, and can be wired. So the flow is read back as
paths (:func:`independent_routes`) and the ceiling is their number, rather than the paths
being thrown away once they have been counted.

Because they are wired, their length is part of the answer. A route this module returns is
cable the design orders: ``synthesizer.backbone.backbone_mesh_paths`` hands them to
``synthesizer.backbone.diverse_mesh_routes``, which draws the backbone-to-backbone links
along them span for span. So the flow is a minimum-cost maximum flow, mileage on each arc:
it returns the largest set of routes no one city's loss takes two of, and out of every set
that size it returns the one running the least cable. Callers may rely on both halves.
Counting cities instead is what put 220 miles of protection between Ashburn and New York
on a 7,471-mile path through Paris (GitHub issue #44), and left roughly a tenth of the
fiber the five tenants' proofs reach for reached for on nothing (GitHub issue #57).

The ceiling is the point where the thing path diversity buys runs out. Below it a node is
leaving built fiber unused; above it every further link must, by the max-flow min-cut
theorem, re-cross a city the node already depends on -- a real cable with real capacity,
but not another independent link, because there is nowhere else for it to go. That is why
it needs no operator input to be the right place to stop, and why it bounds
:func:`synthesizer.validation.diverse_path_count` from above: a set of the node's links
whose failure cities are pairwise disjoint *is* a feasible integral flow here, so no way of
choosing peers can beat the cut.

Under the operator's backup route multiple that argument holds one step less far. Only the
routes the bound allows may be counted, and the largest set of disjoint routes that each
respect a length bound is NP-hard to find, so the number is the best such set this search
came across rather than the most there are (see :func:`independent_routes`). It is a close
answer and not a proved one, and where it errs low the node is named in the design's report
rather than quietly held to less.

Two details the count turns on. A route is normally charged for the peer it ends at as well
as the cities it crosses, since a peer is a city too -- so two disjoint routes to one peer
count once, and a site with peers to spare is not credited with a way out it does not have.
The exception is a backbone holding fewer peers than the tenant asked for paths, where
several routes to one peer are the only answer there is and are counted as the paths they
are (see :func:`routes_per_peer`). And the ceiling depends on which nodes are in the
backbone, because it counts routes to the *other backbone nodes*; it is computed per
candidate backbone set, not once for the map.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Mapping
from dataclasses import dataclass

# One end of a split substrate vertex: ("in", city) and ("out", city) are joined by a
# single unit of capacity, which is what makes a city usable by one route only.
_Node = tuple[str, str]
_Residual = dict[_Node, dict[_Node, int]]
# What each arc of the residual network costs to send a unit down, in miles. A span's arc
# carries the span's length; the arc splitting a city and the arc into the sink carry
# nothing, being bookkeeping rather than cable. Every arc's reverse carries the negative,
# so undoing an earlier choice refunds exactly what it cost.
_Costs = dict[_Node, dict[_Node, float]]
# One arc of the residual network: where it runs from, where it runs to, and how many
# units it was given. The units are carried because an arc a peer takes several routes
# through starts with more than one, so "used" is what it has spent rather than whether
# it has anything left.
_Arc = tuple[_Node, _Node, int]
# An arc as the network is built, before it is added: the same with its mileage.
_Span = tuple[_Node, _Node, float, int]

_SINK: _Node = ("sink", "")

# Slack in miles, absorbing the rounding of a sum of great-circle distances. Five
# millimetres, so it can admit nothing a real span could be refused for.
_TOLERANCE = 1e-6


@dataclass(frozen=True)
class BackupRouteLimit:
    """How far a route may run against the direct distance between its two ends.

    ``multiple`` multiplies the shortest route between a site and the peer a route ends at,
    giving that route its budget: a protect path takes a detour, and this says how much of
    one the operator is buying. It is the tenant's own
    ``backbone.max_backup_route_multiple``, carried in from the config unchanged.
    ``distances`` supplies the shortest-path rows the test needs -- one for the site being
    measured and one for each of its peers, which the callers holding all-pairs distances
    already have (see :func:`synthesizer.graphs.distances_from` for the ones that do not).
    """

    multiple: float
    distances: Mapping[str, Mapping[str, float]]


def _admissible_adjacency(
    node: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: BackupRouteLimit,
) -> dict[str, list[tuple[str, float]]]:
    """``adjacency`` less the spans no route from ``node`` inside the bound could use.

    A span from ``u`` to ``v`` can lie on a route from ``node`` to a peer ``B`` no longer
    than ``B``'s budget only if ``d(node,u) + len(u,v) + d(v,B)`` fits inside it. A span
    failing that for every peer, in both of its orientations, cannot appear on any
    admissible route and is withheld from the flow.

    The test is written as a per-city slack -- the least ``d(v,B) - budget(B)`` over the
    peers -- so the peers are walked once per city rather than once per span, and the spans
    themselves are then a single pass. Both orientations are tested together, so a span
    either survives for both of its endpoints or for neither and the substrate the flow
    sees stays undirected.

    This bounds the fiber and not the finished route, and one peer is enough to keep a
    span: nothing here ties the span it keeps to the peer whose budget kept it, so the flow
    may spend a span admitted on a distant peer's account reaching a near one whose budget
    never covered it. That is why the routes are measured after the flow as well
    (:func:`independent_routes`), and why this stays a first pass rather than the whole
    test. Pruning first is still worth doing: it leaves the flow a maximum flow over the
    fiber this tenant may use, which is what keeps the count a ceiling
    (see :func:`independent_route_ceiling`) rather than the size of some set.

    Erring towards keeping a span is deliberate. A ceiling that is too low lowers the target
    a site is held to and silences the check on it, which is the quiet pass
    :func:`diverse_path_ceilings` refuses to take elsewhere; a ceiling that is slightly too
    high leaves a shortfall for validation to report out loud.

    A limit carrying no distances from ``node`` is refused rather than worked around. Every
    budget would be unmeasurable, every span would fail the test, and the site would score
    a ceiling of zero -- which reads as a site whose fiber can hold nothing and would lower
    its target to nothing on the strength of a caller's omission. That is the same quiet
    pass by another route, so it is an error and says which row is missing.
    """
    if node not in limit.distances:
        raise ValueError(
            f"backup route limit carries no distances from '{node}', so no route out of it "
            "can be measured; pass a row for every site the bound is applied to"
        )
    from_node = limit.distances[node]
    budgets = [
        (peer, limit.multiple * from_node[peer])
        for peer in backbone_ids
        if peer != node and math.isfinite(from_node.get(peer, math.inf))
    ]
    slack = {
        city: min(
            (
                limit.distances.get(peer, {}).get(city, math.inf) - budget
                for peer, budget in budgets
            ),
            default=math.inf,
        )
        for city in adjacency
    }
    admissible: dict[str, list[tuple[str, float]]] = {}
    for city, neighbors in adjacency.items():
        reach = from_node.get(city, math.inf)
        kept = [
            (neighbor, weight)
            for neighbor, weight in neighbors
            if reach + weight + slack.get(neighbor, math.inf) <= _TOLERANCE
            or from_node.get(neighbor, math.inf) + weight
            + slack.get(city, math.inf) <= _TOLERANCE
        ]
        if kept:
            admissible[city] = kept
    return admissible


def _add_capacity(residual: _Residual, costs: _Costs, span: _Span) -> None:
    """Add one directed arc, seeding the reverse arc every search needs.

    The reverse arc starts empty and costs the negative of the forward one, so a later
    round can send a unit back down it and be charged exactly what the earlier round paid.
    """
    tail, head, miles, units = span
    residual.setdefault(tail, {})[head] = units
    residual.setdefault(head, {}).setdefault(tail, 0)
    costs.setdefault(tail, {})[head] = miles
    costs.setdefault(head, {})[tail] = -miles


def _unit_vertex_network(
    node: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    per_peer: int = 1,
) -> tuple[_Residual, _Costs, list[_Arc]]:
    """The residual network whose cheapest max flow out of ``node`` is that node's routes.

    Every city but ``node`` is split into an in and an out side joined by one unit, so a
    route may use it once; ``node`` itself is left unsplit, since all of its own spans are
    available to it. Each substrate span becomes an arc in both directions carrying the
    span's mileage, and every other backbone node feeds the sink -- so a unit of flow is
    one route from ``node`` to a peer, units cannot share a city, and what a unit costs is
    the cable its route runs on.

    ``per_peer`` is how many routes one peer may take (see :func:`routes_per_peer`), and is
    above one only where the backbone holds fewer peers than the tenant asked for paths. At
    one the network is the plain one described above: a peer is split like any other city,
    so a route to a far peer that crosses a nearer one spends that peer's single unit and
    the site cannot then hold a route of its own to it.

    Above one the peers stop being split and become termini only. Several routes may end at
    one peer, which is what the site is short of peers for, and none may cross a peer on the
    way to another -- that route would fail with every route ending there, so counting it
    beside them would credit the site with a way out it does not have.

    The arcs are returned alongside the network with the units each was given, so an arc
    with less capacity left than it started with is one the flow used, which is what lets
    the finished flow be read back as routes rather than only as a count.
    """
    peers = {peer for peer in backbone_ids if peer != node and peer in adjacency}
    termini_only = per_peer > 1
    spans: list[_Span] = [
        (("in", city), ("out", city), 0.0, 1)
        for city in adjacency
        if city != node and not (termini_only and city in peers)
    ]
    spans += [
        (("out", city), ("in", neighbor), weight, 1)
        for city, neighbors in adjacency.items()
        for neighbor, weight in neighbors
    ]
    spans += [
        (("in" if termini_only else "out", peer), _SINK, 0.0, per_peer)
        for peer in sorted(peers)
    ]
    residual: _Residual = {}
    costs: _Costs = {}
    for span in spans:
        _add_capacity(residual, costs, span)
    return residual, costs, [(tail, head, units) for tail, head, _miles, units in spans]


def _cheapest_runs(
    residual: _Residual,
    costs: _Costs,
    potential: dict[_Node, float],
    source: _Node,
) -> tuple[dict[_Node, float], dict[_Node, _Node | None]]:
    """How far the cheapest route to each node runs from ``source``, and how it got there.

    A Dijkstra, which needs every arc to cost nothing less than zero, and the reverse arcs
    a flow leaves behind cost less than zero by construction. ``potential`` is what repairs
    that: each node carries what the cheapest route to it cost in the round before, and an
    arc is walked at ``cost + potential(tail) - potential(head)``, which is never negative
    once the potentials are the previous round's distances and is zero along every arc the
    flow already uses. The distances come back in those repaired terms, and
    :func:`_augmenting_path` is what folds them into the potentials for the next round.

    Both ends of the walk are reported. A node reached is a node with unused capacity
    leading to it, so a sink absent from the second map is a flow with nowhere left to go.
    """
    distance: dict[_Node, float] = {source: 0.0}
    reached: dict[_Node, _Node | None] = {source: None}
    settled: set[_Node] = set()
    queue: list[tuple[float, _Node]] = [(0.0, source)]
    while queue:
        spent, tail = heapq.heappop(queue)
        if tail in settled:
            continue
        settled.add(tail)
        for head, capacity in residual.get(tail, {}).items():
            if capacity <= 0 or head in settled:
                continue
            step = spent + costs[tail][head] + potential[tail] - potential[head]
            if head not in distance or step < distance[head]:
                distance[head] = step
                reached[head] = tail
                heapq.heappush(queue, (step, head))
    return distance, reached


def _augmenting_path(
    residual: _Residual,
    costs: _Costs,
    potential: dict[_Node, float],
    source: _Node,
) -> list[_Node] | None:
    """The least-mileage path of unused capacity from ``source`` to the sink, or None.

    Cheapest rather than shortest in hops, which is the whole of what makes the finished
    flow the least cable of its size: sending each successive unit down the cheapest route
    left to it leaves a flow no rearrangement of the same number of routes can better.

    ``potential`` is brought up to date here, since the next round's Dijkstra cannot run
    without it (see :func:`_cheapest_runs`). A node the walk did not reach keeps the
    potential it had, which costs nothing: no arc with capacity left runs from a reached
    node to an unreached one, or the walk would have reached it.
    """
    distance, reached = _cheapest_runs(residual, costs, potential, source)
    for vertex, run in distance.items():
        potential[vertex] += run
    if _SINK not in reached:
        return None
    path = [_SINK]
    cursor = reached[_SINK]
    while cursor is not None:
        path.append(cursor)
        cursor = reached[cursor]
    return path


def _spent_arcs(residual: _Residual, arcs: list[_Arc]) -> dict[_Node, list[_Node]]:
    """Where the flow went: the heads each tail sent units to, keyed by tail.

    An arc appears once per unit it spent, which is the units it was given less the
    capacity it has left. Almost every arc was given one, so almost every one that spent
    anything appears exactly once; a peer taking several routes is the exception the count
    is written for.
    """
    spent: dict[_Node, list[_Node]] = {}
    for tail, head, units in arcs:
        spent.setdefault(tail, []).extend([head] * (units - residual[tail][head]))
    return spent


def _routes_through(spent: dict[_Node, list[_Node]], source: _Node) -> list[tuple[str, ...]]:
    """Split the finished flow into one city route per unit that left ``source``.

    The walk cannot branch or double back, which is what makes this a plain traversal
    rather than a search. Every transit city is split around a single unit, so a city the
    flow enters has exactly one way out of it and no city can appear on two routes or twice
    on one. A peer taking several routes is the one city several units reach, and every one
    of them leaves it for the sink, so the walk still cannot pick wrongly there.

    Each unit is taken off the tail it arrived on as the walk spends it, which is what
    keeps two units through one peer from both following the first way out.
    """
    routes: list[tuple[str, ...]] = []
    while spent.get(source):
        cities = [source[1]]
        cursor = spent[source].pop(0)
        while cursor != _SINK:
            side, city = cursor
            if side == "in":
                cities.append(city)
            cursor = spent[cursor].pop(0)
        routes.append(tuple(cities))
    return routes


def _span_miles(
    adjacency: dict[str, list[tuple[str, float]]], left: str, right: str
) -> float:
    """The length of the span joining two cities, or infinity if the fiber has none."""
    return next(
        (weight for neighbor, weight in adjacency.get(left, []) if neighbor == right),
        math.inf,
    )


def _route_miles(
    route: tuple[str, ...], adjacency: dict[str, list[tuple[str, float]]]
) -> float:
    """How much cable a finished route runs on, span by span."""
    return sum(
        _span_miles(adjacency, left, right) for left, right in zip(route, route[1:])
    )


def _budget(node: str, peer: str, limit: BackupRouteLimit) -> float:
    """How far a route from ``node`` may run to reach ``peer``."""
    return limit.multiple * limit.distances[node].get(peer, math.inf)


def _withdrawable_span(
    node: str,
    route: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: BackupRouteLimit,
) -> tuple[str, str] | None:
    """The span on ``route`` sitting furthest outside the budget of the peer it ends at.

    A span from ``u`` to ``v`` can lie on some route from ``node`` to that peer within the
    budget only if ``d(node,u) + len(u,v) + d(v,peer)`` fits inside it, which is the test
    :func:`_admissible_adjacency` applies across every peer at once. Here the peer is
    known, so the same arithmetic answers a sharper question, and the span that fails it by
    the most is the one withdrawn.

    The route is walked from the peer end back, so a tie is kept by the span nearest the
    peer, and the fixtures where ties arise say why that is the one to take. A route that
    doubles back on itself is symmetrical about its middle, so the span leaving ``node`` and
    the span arriving at the peer sit equally far outside; the one arriving is the more
    specific to this peer, while the one leaving is the site's whole second way out and may
    be the only fiber reaching somewhere else entirely.

    ``None`` when no single span can be shown impossible. A route can overrun while every
    span on it looks usable, since each span is measured against the shortest way to and
    from its own two ends rather than the way this route actually took, so there is nothing
    to withdraw and the caller stops.

    Every distance read here is finite. A peer the site cannot reach has no budget to
    overrun, so its routes never arrive; and a city on a route to a peer is one that peer
    reaches, over the same undirected fiber, so its row carries the city.
    """
    peer = route[-1]
    budget = _budget(node, peer, limit)
    from_node = limit.distances[node]
    to_peer = limit.distances.get(peer, {})
    worst: tuple[str, str] | None = None
    excess = _TOLERANCE
    for left, right in reversed(list(zip(route, route[1:]))):
        outside = (
            from_node.get(left, math.inf)
            + _span_miles(adjacency, left, right)
            + to_peer.get(right, math.inf)
            - budget
        )
        if outside > excess:
            worst, excess = (left, right), outside
    return worst


def _without_span(
    adjacency: dict[str, list[tuple[str, float]]], left: str, right: str
) -> dict[str, list[tuple[str, float]]]:
    """``adjacency`` with one span withdrawn, in both of its orientations.

    A city left with no fiber at all is dropped rather than kept with an empty list, which
    is the shape :func:`_admissible_adjacency` returns and what the flow expects.
    """
    withdrawn = {(left, right), (right, left)}
    remaining = {
        city: [
            (neighbor, weight)
            for neighbor, weight in neighbors
            if (city, neighbor) not in withdrawn
        ]
        for city, neighbors in adjacency.items()
    }
    return {city: neighbors for city, neighbors in remaining.items() if neighbors}


def _first_withdrawable(
    node: str,
    routes: list[tuple[str, ...]],
    within: list[tuple[str, ...]],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: BackupRouteLimit,
) -> tuple[str, str] | None:
    """One span to withdraw, taken from the first overrunning route that offers one.

    One span goes per pass rather than one per overrunning route, because the flow is
    recomputed afterwards and the routes it comes back with may be different ones: a second
    withdrawal decided against routes that no longer exist would be taking fiber away on the
    strength of nothing.
    """
    for route in routes:
        if route in within:
            continue
        withdrawn = _withdrawable_span(node, route, adjacency, limit)
        if withdrawn is not None:
            return withdrawn
    return None


def _proved_routes(
    node: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    per_peer: int = 1,
) -> list[tuple[str, ...]]:
    """The cheapest maximum flow out of ``node``, read back as the routes it spent.

    One unit at a time, each sent down the least-mileage route still open to it, until no
    unused capacity reaches the sink. The flow is therefore as large as any flow here can
    be -- the count is unchanged by charging for mileage -- and the least cable of the
    flows that size.

    The rounds are bounded by the flow itself, which is bounded by the number of peers
    times ``per_peer``, since every unit that leaves ``node`` ends at a peer's arc into the
    sink and each of those arcs holds that many.
    """
    residual, costs, arcs = _unit_vertex_network(node, backbone_ids, adjacency, per_peer)
    source: _Node = ("out", node)
    # Every node starts owing nothing, which is a valid set of potentials because no arc
    # costs less than zero until a round has sent a unit down one. The source is named
    # alongside the network because a site the substrate carries no fiber for is absent
    # from it, and the walk out of such a site still has to start somewhere.
    potential: dict[_Node, float] = {vertex: 0.0 for vertex in (source, *residual)}
    while True:
        path = _augmenting_path(residual, costs, potential, source)
        if path is None:
            return _routes_through(_spent_arcs(residual, arcs), source)
        for head, tail in zip(path, path[1:]):
            residual[tail][head] -= 1
            residual[head][tail] += 1


@dataclass(frozen=True)
class RouteGround:
    """What a site's ways out are proved against: the peers to reach and the fiber to use.

    The four travel together everywhere a route is proved or counted -- which peers are in
    the backbone decides where a route may end, the fiber decides how it gets there, the
    operator's bound decides how far it may run, and the tenant's number decides whether a
    peer may take more than one. Bundling them says so, and keeps the three entry points
    below to the site being asked about and the ground it stands on.

    ``limit`` of ``None`` leaves every route admissible, which is the behaviour of the
    callers with no tenant in hand -- the backbone search ranking candidate sites, which is
    asking what a site's fiber can do rather than what this tenant is buying.
    """

    backbone_ids: tuple[str, ...]
    adjacency: dict[str, list[tuple[str, float]]]
    limit: BackupRouteLimit | None = None
    paths_wanted: int = 1


def routes_per_peer(node: str, backbone_ids: tuple[str, ...], paths_wanted: int) -> int:
    """How many routes one peer may take, given how many paths the site was asked for.

    A site takes one route to each of as many peers as it can reach, which is what a way
    out of a site is: losing a peer costs the site that way out and no other. Only when
    the backbone holds fewer peers than the tenant asked for paths does a peer take a
    second route, and then it takes no more of them than sharing the shortfall out evenly
    requires.

    Two-Node is the whole of why this is not always one. Its backbone is Ashburn, VA and
    Salt Lake City, UT, so each site has exactly one peer and a tenant asking for two paths
    can only be answered by two routes to it.
    """
    peers = sum(1 for peer in backbone_ids if peer != node)
    return max(1, -(-paths_wanted // peers)) if peers else 1


def independent_routes(node: str, ground: RouteGround) -> list[tuple[str, ...]]:
    """The shortest set of the most routes from ``node`` no one city's loss takes two of.

    Each runs from ``node`` to a peer, and no city carries two of them -- a max flow with
    unit vertex capacities (see :func:`_unit_vertex_network`), pushed one route at a time
    until no unused capacity reaches the sink, then read back off the arcs it spent. Each
    augmenting path carries exactly one route.

    ``ground.paths_wanted`` is how many paths the tenant asked this site for, and decides
    only whether a peer may take more than one route (see :func:`routes_per_peer`). Where
    the backbone holds at least that many peers it changes nothing: the routes run to
    distinct peers, which is the answer this function has always given. Where it holds
    fewer -- a two-site backbone asked for two paths -- the peers take the shortfall between
    them, and the routes to one peer share that peer and no other city.

    It is not a cap on what comes back. This counts what the fiber can carry, and how many
    of them the mesh then draws is the tenant's number applied by
    :func:`synthesizer.backbone.backbone_mesh_paths`.

    Of the many sets that size, the one returned is the one running the least cable. Each
    round takes the cheapest route left rather than the one crossing the fewest cities (see
    :func:`_augmenting_path`), which makes the whole thing a minimum-cost maximum flow. How
    many routes come back is unaffected: the flow is maximised first and priced second, so
    a crossing that is the only way to one more peer is still taken however long it is.

    These are the links the node could hold, not the links it has. Where the mesh has left
    a node short of what its fiber allows, they are what it is short of, and wiring them is
    what closes the gap -- which is the reason this returns the routes rather than only
    counting them. It is also why their length is worth minimising: the mesh lays them
    verbatim, so a route proved here is cable somebody buys.

    ``limit`` bounds how far a route may run against the direct distance to the peer it
    ends at, and is a separate question from which of the cheapest routes are taken. A
    maximum flow maximises the number of routes before it minimises their mileage, so where
    an ocean crossing is the only way to one more peer the cheapest set still holds it --
    over the five tenants' maps the cheapest sets run eight to nine routes per tenant past
    three times the direct distance, the worst of them Hillsboro to Seattle at 59.83 times.
    Omitting the bound leaves those counted, which is what the graph-shaped callers with no
    tenant in hand rely on.

    With it, the fiber is pruned first (see :func:`_admissible_adjacency`) and then every
    route the flow assembles is measured against the budget of the peer it actually reached.
    The prune alone is not enough, because it keeps a span that fits any one peer's budget
    and the flow may then spend that span reaching a different peer with a much smaller one.
    Where a route overruns, the span furthest outside that peer's budget is withdrawn (see
    :func:`_withdrawable_span`) and the flow is run again over what is left -- the withdrawn
    span may still serve another peer on a later pass, so this narrows the search rather
    than the fiber. It repeats until every route comes back inside its budget or no span can
    be shown impossible, and what it returns is the largest set of within-budget routes any
    pass produced.

    Keeping the largest rather than the last is what stops the repair costing more than the
    defect. A withdrawn span can be the only fiber reaching a genuinely distant peer as well
    as the shortcut a near one was routed through, so a pass can come back with fewer honest
    routes than the pass before it. A count slightly too high leaves a shortfall for
    validation to report out loud; a count too low lowers the target and silences the check
    on it, which is the worse of the two by a distance.

    It is still not exact, and cannot be. Asking for the largest set of vertex-disjoint
    routes that each respect a length bound is NP-hard, so no exact answer is available at
    any price; this bounds the routes as well as the fiber, and still bounds them from
    above.
    """
    backbone_ids, adjacency = ground.backbone_ids, ground.adjacency
    limit = ground.limit
    per_peer = routes_per_peer(node, backbone_ids, ground.paths_wanted)
    if limit is None:
        return _proved_routes(node, backbone_ids, adjacency, per_peer)
    admissible = _admissible_adjacency(node, backbone_ids, adjacency, limit)
    best: list[tuple[str, ...]] = []
    while True:
        routes = _proved_routes(node, backbone_ids, admissible, per_peer)
        within = [
            route
            for route in routes
            if _route_miles(route, admissible)
            <= _budget(node, route[-1], limit) + _TOLERANCE
        ]
        if len(within) > len(best):
            best = within
        if len(within) == len(routes):
            return best
        withdrawn = _first_withdrawable(node, routes, within, admissible, limit)
        if withdrawn is None:
            return best
        admissible = _without_span(admissible, *withdrawn)


def independent_route_ceiling(node: str, ground: RouteGround) -> int:
    """The most links ``node`` could hold that no single city's loss takes two of.

    The number of routes :func:`independent_routes` finds. Unbounded that is the max flow of
    the unit-capacity network, and so the size of the smallest set of cities whose loss
    would cut ``node`` off from the rest of the backbone.

    A node the substrate does not carry, or one whose peers it cannot reach, scores zero:
    it can hold no independent link, which is the truth about it. The count never exceeds
    the number of other backbone nodes, since that is how many arcs feed the sink.

    ``limit`` bounds how far the routes counted may run (see :func:`independent_routes`).
    A route the operator's bound refuses is not protection the site can be credited with,
    so counting it would say a chokepointed site can hold links that it cannot. Under a
    bound the number is the best set that search found rather than a proved maximum, and
    the cut it corresponds to is over the fiber that search was left with.

    ``ground.paths_wanted`` lets a peer carry more than one route where the backbone holds
    too few peers to answer the tenant any other way (see :func:`independent_routes`).
    Without it a two-site backbone scores one however much diverse fiber joins the two, and
    a target taken from that ceiling asks each site for the single unprotected circuit it
    already has.
    """
    return len(independent_routes(node, ground))


def diverse_path_ceilings(ground: RouteGround) -> dict[str, int]:
    """Each backbone node's ceiling, computed over the substrate they all sit on.

    One max flow per backbone node. Each is cheap at the sizes here: the flow stops at the
    number of peers, so the augmenting search runs a handful of times however large the
    carrier graph behind it is.

    Only nodes the substrate carries get an entry. A node it says nothing about would score
    zero, and reporting zero would lower that node's target to nothing and silence every
    check on it -- but no fiber in the inputs is absence of evidence, not evidence of a
    ceiling, and a target lowered on it is exactly the quiet pass a computed ceiling has to
    avoid. Such a node is left out, and whoever holds it to a target holds it to the full
    configured degree.

    Membership is judged on the substrate as given rather than on what the bound leaves of
    it, so a site whose every span the bound withholds is reported as a ceiling of zero
    rather than left out. The two say different things: the substrate carries that site and
    the answer about it is that nothing it can reach is worth reaching, which is a finding
    and not a silence.

    ``ground.paths_wanted`` is the tenant's own number, carried through so a site on a
    backbone with too few peers is scored on the routes it could really hold rather than on
    the one route per peer a larger backbone would give it (see :func:`independent_routes`).
    """
    return {
        node: independent_route_ceiling(node, ground)
        for node in ground.backbone_ids
        if node in ground.adjacency
    }
