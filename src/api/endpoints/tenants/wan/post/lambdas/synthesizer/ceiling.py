"""How many independently failing links a backbone node's fiber can actually carry.

The mesh degree asks for links that fail independently: two links leaving a node through
one city are one link the moment that city goes. So the question "how many links should
this node have" is really "how many routes out of it reach the rest of the backbone
without sharing a city", and that is a fact about the substrate rather than a number
anyone chooses. This module computes it, once per backbone node, and calls it the node's
ceiling.

The routes behind the number are worth as much as the number. A count says a node is
short; the routes say what it is short of, and can be wired. So the flow is read back as
paths (:func:`independent_routes`) and the ceiling is their number, rather than the paths
being thrown away once they have been counted.

The ceiling is the exact point where the thing the mesh degree buys runs out. Below it a
node is leaving built fiber unused; above it every further link must, by the max-flow
min-cut theorem, re-cross a city the node already depends on -- a real cable with real
capacity, but not another independent link, because there is nowhere else for it to go.
That is why it needs no operator input to be the right place to stop, and why it bounds
:func:`synthesizer.validation.independent_mesh_degree` from above: a set of the node's
links whose failure cities are pairwise disjoint *is* a feasible integral flow here, so
no way of choosing peers can beat the cut.

Two details the count turns on. A route is charged for the peer it ends at as well as the
cities it crosses, since a peer is a city too -- so two disjoint routes to one peer count
once. And the ceiling depends on which nodes are in the backbone, because it counts
routes to the *other backbone nodes*; it is computed per candidate backbone set, not once
for the map.
"""

from __future__ import annotations

from collections import deque

# One end of a split substrate vertex: ("in", city) and ("out", city) are joined by a
# single unit of capacity, which is what makes a city usable by one route only.
_Node = tuple[str, str]
_Residual = dict[_Node, dict[_Node, int]]
_Arc = tuple[_Node, _Node]

_SINK: _Node = ("sink", "")


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
    """
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
) -> int:
    """The most links ``node`` could hold that no single city's loss takes two of.

    The number of routes :func:`independent_routes` finds, which is the max flow of the
    unit-capacity network and so the size of the smallest set of cities whose loss would
    cut ``node`` off from the rest of the backbone.

    A node the substrate does not carry, or one whose peers it cannot reach, scores zero:
    it can hold no independent link, which is the truth about it. The count never exceeds
    the number of other backbone nodes, since that is how many arcs feed the sink.
    """
    return len(independent_routes(node, backbone_ids, adjacency))


def mesh_degree_ceilings(
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
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
    """
    return {
        node: independent_route_ceiling(node, backbone_ids, adjacency)
        for node in backbone_ids
        if node in adjacency
    }
