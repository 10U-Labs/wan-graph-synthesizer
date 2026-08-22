from __future__ import annotations

import heapq
import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from synthesizer.graphs import reachable_over

_Node = tuple[str, str]
_Residual = dict[_Node, dict[_Node, int]]
_Costs = dict[_Node, dict[_Node, float]]
_Arc = tuple[_Node, _Node, int]
_NewArc = tuple[_Node, _Node, float, int]

_SINK: _Node = ("sink", "")

_TOLERANCE = 1e-6


@dataclass(frozen=True)
class BackupPathLimit:
    multiple: float
    distances: Mapping[str, Mapping[str, float]]


def _admissible_adjacency(
    node: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: BackupPathLimit,
) -> dict[str, list[tuple[str, float]]]:
    if node not in limit.distances:
        raise ValueError(
            f"backup path limit carries no distances from '{node}', so no path out of it "
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


def _add_capacity(residual: _Residual, costs: _Costs, arc: _NewArc) -> None:
    tail, head, miles, units = arc
    residual.setdefault(tail, {})[head] = units
    residual.setdefault(head, {}).setdefault(tail, 0)
    costs.setdefault(tail, {})[head] = miles
    costs.setdefault(head, {})[tail] = -miles


def _unit_site_network(
    node: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    per_peer: int = 1,
) -> tuple[_Residual, _Costs, list[_Arc]]:
    peers = {peer for peer in backbone_ids if peer != node and peer in adjacency}
    termini_only = per_peer > 1
    new_arcs: list[_NewArc] = [
        (("in", city), ("out", city), 0.0, 1)
        for city in adjacency
        if city != node and not (termini_only and city in peers)
    ]
    new_arcs += [
        (("out", city), ("in", neighbor), weight, 1)
        for city, neighbors in adjacency.items()
        for neighbor, weight in neighbors
    ]
    new_arcs += [
        (("in" if termini_only else "out", peer), _SINK, 0.0, per_peer)
        for peer in sorted(peers)
    ]
    residual: _Residual = {}
    costs: _Costs = {}
    for arc in new_arcs:
        _add_capacity(residual, costs, arc)
    return residual, costs, [(tail, head, units) for tail, head, _miles, units in new_arcs]


def _cheapest_runs(
    residual: _Residual,
    costs: _Costs,
    potential: dict[_Node, float],
    source: _Node,
) -> tuple[dict[_Node, float], dict[_Node, _Node | None]]:
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
    distance, reached = _cheapest_runs(residual, costs, potential, source)
    for site, run in distance.items():
        potential[site] += run
    if _SINK not in reached:
        return None
    path = [_SINK]
    cursor = reached[_SINK]
    while cursor is not None:
        path.append(cursor)
        cursor = reached[cursor]
    return path


def _spent_arcs(residual: _Residual, arcs: list[_Arc]) -> dict[_Node, list[_Node]]:
    spent: dict[_Node, list[_Node]] = {}
    for tail, head, units in arcs:
        spent.setdefault(tail, []).extend([head] * (units - residual[tail][head]))
    return spent


def _paths_through(spent: dict[_Node, list[_Node]], source: _Node) -> list[tuple[str, ...]]:
    paths: list[tuple[str, ...]] = []
    while spent.get(source):
        cities = [source[1]]
        cursor = spent[source].pop(0)
        while cursor != _SINK:
            side, city = cursor
            if side == "in":
                cities.append(city)
            cursor = spent[cursor].pop(0)
        paths.append(tuple(cities))
    return paths


def _fiber_segment_miles(
    adjacency: dict[str, list[tuple[str, float]]], left: str, right: str
) -> float:
    return next(
        (weight for neighbor, weight in adjacency.get(left, []) if neighbor == right),
        math.inf,
    )


def _path_miles(
    path: tuple[str, ...], adjacency: dict[str, list[tuple[str, float]]]
) -> float:
    return sum(
        _fiber_segment_miles(adjacency, left, right) for left, right in zip(path, path[1:])
    )


def _budget(node: str, peer: str, limit: BackupPathLimit) -> float:
    return limit.multiple * limit.distances[node].get(peer, math.inf)


def _withdrawable_fiber_segment(
    node: str,
    path: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: BackupPathLimit,
) -> tuple[str, str] | None:
    peer = path[-1]
    budget = _budget(node, peer, limit)
    from_node = limit.distances[node]
    to_peer = limit.distances.get(peer, {})
    worst: tuple[str, str] | None = None
    excess = _TOLERANCE
    for left, right in reversed(list(zip(path, path[1:]))):
        outside = (
            from_node.get(left, math.inf)
            + _fiber_segment_miles(adjacency, left, right)
            + to_peer.get(right, math.inf)
            - budget
        )
        if outside > excess:
            worst, excess = (left, right), outside
    return worst


def _without_fiber_segment(
    adjacency: dict[str, list[tuple[str, float]]], left: str, right: str
) -> dict[str, list[tuple[str, float]]]:
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
    paths: list[tuple[str, ...]],
    within: list[tuple[str, ...]],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: BackupPathLimit,
) -> tuple[str, str] | None:
    for path in paths:
        if path in within:
            continue
        withdrawn = _withdrawable_fiber_segment(node, path, adjacency, limit)
        if withdrawn is not None:
            return withdrawn
    return None


def _proved_paths(
    node: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    per_peer: int = 1,
) -> list[tuple[str, ...]]:
    residual, costs, arcs = _unit_site_network(node, backbone_ids, adjacency, per_peer)
    source: _Node = ("out", node)
    potential: dict[_Node, float] = {site: 0.0 for site in (source, *residual)}
    while True:
        path = _augmenting_path(residual, costs, potential, source)
        if path is None:
            return _paths_through(_spent_arcs(residual, arcs), source)
        for head, tail in zip(path, path[1:]):
            residual[tail][head] -= 1
            residual[head][tail] += 1


@dataclass(frozen=True)
class PathProofInputs:
    backbone_ids: tuple[str, ...]
    adjacency: dict[str, list[tuple[str, float]]]
    limit: BackupPathLimit | None = None
    paths_wanted: int = 1
    seat_cap: int | None = None
    fiber_by_carrier: dict[str, dict[str, list[tuple[str, float]]]] = field(
        default_factory=dict
    )
    terrestrial: dict[str, list[tuple[str, float]]] = field(default_factory=dict)


def paths_per_peer(seat_cap: int | None, seats: int, paths_wanted: int) -> int:
    peers = (seat_cap if seat_cap is not None else seats) - 1
    return max(1, -(-paths_wanted // peers)) if peers > 0 else 1


def _paths_over(
    node: str,
    inputs: PathProofInputs,
    adjacency: dict[str, list[tuple[str, float]]],
    per_peer: int,
) -> list[tuple[str, ...]]:
    limit = inputs.limit
    backbone_ids = inputs.backbone_ids
    if limit is None:
        return _proved_paths(node, backbone_ids, adjacency, per_peer)
    admissible = _admissible_adjacency(node, backbone_ids, adjacency, limit)
    best: list[tuple[str, ...]] = []
    while True:
        paths = _proved_paths(node, backbone_ids, admissible, per_peer)
        within = [
            path
            for path in paths
            if _path_miles(path, admissible)
            <= _budget(node, path[-1], limit) + _TOLERANCE
        ]
        if len(within) > len(best):
            best = within
        if len(within) == len(paths):
            return best
        withdrawn = _first_withdrawable(node, paths, within, admissible, limit)
        if withdrawn is None:
            return best
        admissible = _without_fiber_segment(admissible, *withdrawn)


def _no_city_twice(
    node: str,
    found: list[tuple[str, ...]],
    inputs: PathProofInputs,
    per_peer: int,
) -> list[tuple[str, ...]]:
    peers = {peer for peer in inputs.backbone_ids if peer != node}
    termini_only = per_peer > 1
    spent: set[str] = set()
    ends: dict[str, int] = {}
    seen: set[tuple[str, ...]] = set()
    kept: list[tuple[str, ...]] = []
    ordered = sorted(found, key=lambda one: (_path_miles(one, inputs.adjacency), one))
    for path in ordered:
        if path in seen:
            continue
        seen.add(path)
        interior = set(path[1:-1])
        end = path[-1]
        if interior & spent or (termini_only and interior & peers):
            continue
        if end in spent or (termini_only and ends.get(end, 0) >= per_peer):
            continue
        spent |= interior
        if termini_only:
            ends[end] = ends.get(end, 0) + 1
        else:
            spent.add(end)
        kept.append(path)
    return kept


def independent_paths(node: str, inputs: PathProofInputs) -> list[tuple[str, ...]]:
    return [path for _carrier, path in _ways_out_and_their_carriers(node, inputs)]


def _peers_over_land(node: str, inputs: PathProofInputs) -> frozenset[str]:
    joined = reachable_over(inputs.terrestrial).get(node, frozenset())
    return joined & frozenset(peer for peer in inputs.backbone_ids if peer != node)


def _over_land(
    node: str, inputs: PathProofInputs, adjacency: dict[str, list[tuple[str, float]]]
) -> dict[str, list[tuple[str, float]]]:
    if not _peers_over_land(node, inputs):
        return adjacency
    on_land = {
        city: {neighbor for neighbor, _weight in neighbors}
        for city, neighbors in inputs.terrestrial.items()
    }
    kept = {
        city: [
            (neighbor, weight)
            for neighbor, weight in neighbors
            if neighbor in on_land.get(city, frozenset())
        ]
        for city, neighbors in adjacency.items()
    }
    return {city: neighbors for city, neighbors in kept.items() if neighbors}


def _paths_over_each_carrier(
    node: str, inputs: PathProofInputs, per_peer: int
) -> dict[str, list[tuple[str, ...]]]:
    if not inputs.fiber_by_carrier:
        return {
            "": _paths_over(
                node, inputs, _over_land(node, inputs, inputs.adjacency), per_peer
            )
        }
    return {
        carrier: _paths_over(node, inputs, _over_land(node, inputs, adjacency), per_peer)
        for carrier, adjacency in sorted(inputs.fiber_by_carrier.items())
        if node in adjacency
    }


def _per_peer(inputs: PathProofInputs) -> int:
    return paths_per_peer(
        inputs.seat_cap, len(inputs.backbone_ids), inputs.paths_wanted
    )


def _kept_with_their_carriers(
    node: str,
    inputs: PathProofInputs,
    by_carrier: dict[str, list[tuple[str, ...]]],
    per_peer: int,
) -> list[tuple[str, tuple[str, ...]]]:
    seller: dict[tuple[str, ...], str] = {}
    for carrier, paths in sorted(by_carrier.items()):
        for path in paths:
            seller.setdefault(path, carrier)
    if not inputs.fiber_by_carrier:
        return [("", path) for path in by_carrier[""]]
    found = [path for _carrier, paths in sorted(by_carrier.items()) for path in paths]
    return [
        (seller[path], path)
        for path in _no_city_twice(node, found, inputs, per_peer)
    ]


def _ways_out_and_their_carriers(
    node: str, inputs: PathProofInputs
) -> list[tuple[str, tuple[str, ...]]]:
    per_peer = _per_peer(inputs)
    return _kept_with_their_carriers(
        node, inputs, _paths_over_each_carrier(node, inputs, per_peer), per_peer
    )


def ways_out_by_carrier_and_peer(
    node: str, inputs: PathProofInputs
) -> dict[tuple[str, str], int]:
    per_peer = _per_peer(inputs)
    by_carrier = _paths_over_each_carrier(node, inputs, per_peer)
    counted: dict[tuple[str, str], int] = {}
    for carrier, path in _kept_with_their_carriers(node, inputs, by_carrier, per_peer):
        counted[(carrier, path[-1])] = counted.get((carrier, path[-1]), 0) + 1
    return counted


def independent_path_ceiling(node: str, inputs: PathProofInputs) -> int:
    return len(independent_paths(node, inputs))


def diverse_path_ceilings(inputs: PathProofInputs) -> dict[str, int]:
    return {
        node: independent_path_ceiling(node, inputs)
        for node in inputs.backbone_ids
        if node in inputs.adjacency
    }
