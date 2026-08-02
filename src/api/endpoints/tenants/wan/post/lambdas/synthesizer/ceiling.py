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

The ceiling is the exact point where the thing path diversity buys runs out. Below it a
node is leaving built fiber unused; above it every further link must, by the max-flow
min-cut theorem, re-cross a city the node already depends on -- a real cable with real
capacity, but not another independent link, because there is nowhere else for it to go.
That is why it needs no operator input to be the right place to stop, and why it bounds
:func:`synthesizer.validation.diverse_path_count` from above: a set of the node's
links whose failure cities are pairwise disjoint *is* a feasible integral flow here, so
no way of choosing peers can beat the cut.

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

    This bounds the fiber and not the finished route, which is a relaxation rather than an
    exact filter: a route assembled entirely from surviving spans can still overrun its
    budget. It is the right trade rather than a corner cut. Asking for the largest set of
    disjoint routes that each respect a length bound is NP-hard, so an exact answer is not
    available at any price, while pruning first leaves the flow a maximum flow over the
    fiber this tenant may use -- which is what makes the count it returns a true ceiling
    (see :func:`independent_route_ceiling`) rather than the size of some set.

    Erring towards keeping a span is deliberate for the same reason. A ceiling that is too
    low lowers the target a site is held to and silences the check on it, which is the
    quiet pass :func:`diverse_path_ceilings` refuses to take elsewhere; a ceiling that is
    slightly too high leaves a shortfall for validation to report out loud.

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
    ends at, and is applied to the fiber before the flow rather than to the routes after it
    (see :func:`_admissible_adjacency`). Without it the flow reads no distance at all: a
    span is one unit of a city's capacity whether it is four miles long or four thousand,
    and the breadth-first augmenting search actively prefers the long one, since it takes
    the route crossing the fewest cities each round and an ocean crossing is the shortest
    such route between two coasts there is. Omitting it leaves that behaviour exactly,
    which is what the graph-shaped callers with no tenant in hand rely on.
    """
    if limit is not None:
        adjacency = _admissible_adjacency(node, backbone_ids, adjacency, limit)
    residual, arcs = _unit_vertex_network(node, backbone_ids, adjacency)
    source: _Node = ("out", node)
    while True:
        path = _augmenting_path(residual, source)
        if path is None:
            return _routes_through(_spent_arcs(residual, arcs), source)
        for head, tail in zip(path, path[1:]):
            residual[tail][head] -= 1
            residual[head][tail] += 1


def independent_route_ceiling(
    node: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: StretchLimit | None = None,
) -> int:
    """The most links ``node`` could hold that no single city's loss takes two of.

    The number of routes :func:`independent_routes` finds, which is the max flow of the
    unit-capacity network and so the size of the smallest set of cities whose loss would
    cut ``node`` off from the rest of the backbone.

    A node the substrate does not carry, or one whose peers it cannot reach, scores zero:
    it can hold no independent link, which is the truth about it. The count never exceeds
    the number of other backbone nodes, since that is how many arcs feed the sink.

    ``limit`` bounds how far the routes counted may run (see :func:`independent_routes`).
    A route the operator's bound refuses is not protection the site can be credited with,
    so counting it would say a chokepointed site can hold links that it cannot.
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
