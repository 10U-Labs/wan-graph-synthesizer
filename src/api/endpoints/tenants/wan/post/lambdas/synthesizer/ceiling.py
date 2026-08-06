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

The ceiling is the point where the thing path diversity buys runs out. Below it a node is
leaving built fiber unused; above it every further link must, by the max-flow min-cut
theorem, re-cross a city the node already depends on -- a real cable with real capacity,
but not another independent link, because there is nowhere else for it to go. That is why
it needs no operator input to be the right place to stop, and why it bounds
:func:`synthesizer.validation.diverse_path_count` from above: a set of the node's links
whose failure cities are pairwise disjoint *is* a feasible integral flow here, so no way of
choosing peers can beat the cut.

Under the operator's stretch bound that argument holds one step less far. Only the routes
the bound allows may be counted, and the largest set of disjoint routes that each respect a
length bound is NP-hard to find, so the number is the best such set this module's search
came across rather than the most there are (see :func:`independent_routes`). It is a close
answer and not a proved one, and where it errs low the node is named in the design's report
rather than quietly held to less.

Two details the count turns on. A route is charged for the peer it ends at as well as the
cities it crosses, since a peer is a city too -- so two disjoint routes to one peer count
once. And the ceiling depends on which nodes are in the backbone, because it counts
routes to the *other backbone nodes*; it is computed per candidate backbone set, not once
for the map.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

# One end of a split substrate vertex: ("in", city) and ("out", city) are joined by a
# single unit of capacity, which is what makes a city usable by one route only.
_Node = tuple[str, str]
_Residual = dict[_Node, dict[_Node, int]]
_Arc = tuple[_Node, _Node]

_SINK: _Node = ("sink", "")

# Slack in miles, absorbing the rounding of a sum of great-circle distances. Five
# millimetres, so it can admit nothing a real span could be refused for.
_TOLERANCE = 1e-6


@dataclass(frozen=True)
class StretchLimit:
    """How far a route may run against the direct distance between its two ends.

    ``stretch`` multiplies the shortest route between a site and the peer a route ends at,
    giving that route its budget: a protect path takes a detour, and this says how much of
    one the operator is buying. ``distances`` supplies the shortest-path rows the test
    needs -- one for the site being measured and one for each of its peers, which the
    callers holding all-pairs distances already have (see
    :func:`synthesizer.graphs.distances_from` for the ones that do not).
    """

    stretch: float
    distances: Mapping[str, Mapping[str, float]]


def _admissible_adjacency(
    node: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: StretchLimit,
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
            f"stretch limit carries no distances from '{node}', so no route out of it can "
            "be measured; pass a row for every site the bound is applied to"
        )
    from_node = limit.distances[node]
    budgets = [
        (peer, limit.stretch * from_node[peer])
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


def _add_capacity(residual: _Residual, tail: _Node, head: _Node, amount: int) -> None:
    """Add a directed arc, seeding the reverse arc every augmenting search needs."""
    forward = residual.setdefault(tail, {})
    forward[head] = forward.get(head, 0) + amount
    residual.setdefault(head, {}).setdefault(tail, 0)


def _unit_vertex_network(
    node: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
) -> tuple[_Residual, list[_Arc]]:
    """The residual network whose max flow out of ``node`` is that node's ceiling.

    Every city but ``node`` is split into an in and an out side joined by one unit, so a
    route may use it once; ``node`` itself is left unsplit, since all of its own spans are
    available to it. Each substrate span becomes an arc in both directions, and every
    other backbone node's out side feeds the sink -- so a unit of flow is one route from
    ``node`` to a distinct peer, and units cannot share a city.

    The arcs are returned alongside the network. Every one of them carries a single unit,
    so an arc with none of its capacity left is an arc the flow used, which is what lets
    the finished flow be read back as routes rather than only as a count.
    """
    arcs: list[_Arc] = [
        (("in", city), ("out", city)) for city in adjacency if city != node
    ]
    arcs += [
        (("out", city), ("in", neighbor))
        for city, neighbors in adjacency.items()
        for neighbor, _weight in neighbors
    ]
    arcs += [
        (("out", peer), _SINK)
        for peer in backbone_ids
        if peer != node and peer in adjacency
    ]
    residual: _Residual = {}
    for tail, head in arcs:
        _add_capacity(residual, tail, head, 1)
    return residual, arcs


def _augmenting_path(residual: _Residual, source: _Node) -> list[_Node] | None:
    """One breadth-first path of unused capacity from ``source`` to the sink, or None.

    Breadth-first so the shortest augmenting path is taken each round, which is what keeps
    the number of rounds bounded by the flow itself (Edmonds--Karp).
    """
    reached: dict[_Node, _Node | None] = {source: None}
    queue: deque[_Node] = deque([source])
    while queue:
        tail = queue.popleft()
        for head, capacity in residual.get(tail, {}).items():
            if capacity <= 0 or head in reached:
                continue
            reached[head] = tail
            if head == _SINK:
                path = [head]
                cursor: _Node | None = tail
                while cursor is not None:
                    path.append(cursor)
                    cursor = reached[cursor]
                return path
            queue.append(head)
    return None


def _spent_arcs(residual: _Residual, arcs: list[_Arc]) -> dict[_Node, list[_Node]]:
    """Where the flow went: the heads each tail sent its unit to, keyed by tail.

    Every arc was given a single unit, so one with nothing left is one the flow used.
    """
    spent: dict[_Node, list[_Node]] = {}
    for tail, head in arcs:
        if residual[tail][head] == 0:
            spent.setdefault(tail, []).append(head)
    return spent


def _routes_through(spent: dict[_Node, list[_Node]], source: _Node) -> list[tuple[str, ...]]:
    """Split the finished flow into one city route per unit that left ``source``.

    The walk cannot branch or double back, which is what makes this a plain traversal
    rather than a search. Every city but the source is split around a single unit, so a
    city the flow enters has exactly one way out of it, and no city can appear on two
    routes or twice on one. Each unit leaving the source therefore runs to the sink, and
    there are as many of them as the flow is worth.
    """
    routes: list[tuple[str, ...]] = []
    for first in spent.get(source, []):
        cities = [source[1]]
        cursor = first
        while cursor != _SINK:
            side, city = cursor
            if side == "in":
                cities.append(city)
            cursor = spent[cursor][0]
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


def _budget(node: str, peer: str, limit: StretchLimit) -> float:
    """How far a route from ``node`` may run to reach ``peer``."""
    return limit.stretch * limit.distances[node].get(peer, math.inf)


def _withdrawable_span(
    node: str,
    route: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: StretchLimit,
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
    limit: StretchLimit,
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
) -> list[tuple[str, ...]]:
    """One maximum flow out of ``node``, read back as the routes it spent its arcs on."""
    residual, arcs = _unit_vertex_network(node, backbone_ids, adjacency)
    source: _Node = ("out", node)
    while True:
        path = _augmenting_path(residual, source)
        if path is None:
            return _routes_through(_spent_arcs(residual, arcs), source)
        for head, tail in zip(path, path[1:]):
            residual[tail][head] -= 1
            residual[head][tail] += 1


def independent_routes(
    node: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: StretchLimit | None = None,
) -> list[tuple[str, ...]]:
    """The most routes from ``node`` that no single city's loss takes two of.

    Each runs from ``node`` to a distinct peer, and no city carries two of them -- a max
    flow with unit vertex capacities (see :func:`_unit_vertex_network`), pushed one route
    at a time until no unused capacity reaches the sink, then read back off the arcs it
    spent. Every unit of capacity is one, so each augmenting path carries exactly one
    route.

    These are the links the node could hold, not the links it has. Where the mesh has left
    a node short of what its fiber allows, they are what it is short of, and wiring them is
    what closes the gap -- which is the reason this returns the routes rather than only
    counting them.

    ``limit`` bounds how far a route may run against the direct distance to the peer it
    ends at. Without it the flow reads no distance at all: a span is one unit of a city's
    capacity whether it is four miles long or four thousand, and the breadth-first
    augmenting search actively prefers the long one, since it takes the route crossing the
    fewest cities each round and an ocean crossing is the shortest such route between two
    coasts there is. Omitting it leaves that behaviour exactly, which is what the
    graph-shaped callers with no tenant in hand rely on.

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
    if limit is None:
        return _proved_routes(node, backbone_ids, adjacency)
    admissible = _admissible_adjacency(node, backbone_ids, adjacency, limit)
    best: list[tuple[str, ...]] = []
    while True:
        routes = _proved_routes(node, backbone_ids, admissible)
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


def independent_route_ceiling(
    node: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: StretchLimit | None = None,
) -> int:
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
    """
    return len(independent_routes(node, backbone_ids, adjacency, limit))


def diverse_path_ceilings(
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: StretchLimit | None = None,
) -> dict[str, int]:
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
    """
    return {
        node: independent_route_ceiling(node, backbone_ids, adjacency, limit)
        for node in backbone_ids
        if node in adjacency
    }
