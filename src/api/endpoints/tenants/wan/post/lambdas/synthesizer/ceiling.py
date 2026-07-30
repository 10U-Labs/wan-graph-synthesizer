"""How many independently failing links a backbone node's fiber can actually carry.

The mesh degree asks for links that fail independently: two links leaving a node through
one city are one link the moment that city goes. So the question "how many links should
this node have" is really "how many routes out of it reach the rest of the backbone
without sharing a city", and that is a fact about the substrate rather than a number
anyone chooses. This module computes it, once per backbone node, and calls it the node's
ceiling.

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
) -> _Residual:
    """The residual network whose max flow out of ``node`` is that node's ceiling.

    Every city but ``node`` is split into an in and an out side joined by one unit, so a
    route may use it once; ``node`` itself is left unsplit, since all of its own spans are
    available to it. Each substrate span becomes an arc in both directions, and every
    other backbone node's out side feeds the sink -- so a unit of flow is one route from
    ``node`` to a distinct peer, and units cannot share a city.
    """
    residual: _Residual = {}
    for city in adjacency:
        if city != node:
            _add_capacity(residual, ("in", city), ("out", city), 1)
    for city, neighbors in adjacency.items():
        for neighbor, _weight in neighbors:
            _add_capacity(residual, ("out", city), ("in", neighbor), 1)
    for peer in backbone_ids:
        if peer != node and peer in adjacency:
            _add_capacity(residual, ("out", peer), _SINK, 1)
    return residual


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


def independent_route_ceiling(
    node: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
) -> int:
    """The most links ``node`` could hold that no single city's loss takes two of.

    The largest number of routes from ``node`` to the rest of the backbone that share no
    intermediate city and end at distinct peers -- a max flow with unit vertex capacities
    (see :func:`_unit_vertex_network`), pushed one route at a time until no unused capacity
    reaches the sink. Every unit of capacity is one, so each augmenting path carries
    exactly one route and the flow is the number of rounds.

    A node the substrate does not carry, or one whose peers it cannot reach, scores zero:
    it can hold no independent link, which is the truth about it. The count never exceeds
    the number of other backbone nodes, since that is how many arcs feed the sink.
    """
    residual = _unit_vertex_network(node, backbone_ids, adjacency)
    source: _Node = ("out", node)
    routes = 0
    while True:
        path = _augmenting_path(residual, source)
        if path is None:
            return routes
        for head, tail in zip(path, path[1:]):
            residual[tail][head] -= 1
            residual[head][tail] += 1
        routes += 1


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
