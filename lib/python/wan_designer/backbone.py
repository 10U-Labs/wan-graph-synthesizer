"""Select and route the core-to-core backbone.

The backbone is a minimum-mileage subgraph of the full core mesh that keeps each
core at a degree floor while staying 2-edge-connected, with any operator-forced
core-core pairs pinned in. These helpers are split from the optimizer so the
backbone concern stays cohesive and the optimizer module stays bounded.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from wan_designer.model import PathUse, PhysicalEdge, edge_key
from wan_designer.graphs import is_two_edge_connected, reconstruct_path


def path_geometry_miles(
    path: tuple[str, ...],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> float:
    """Sum the per-span straight-line estimate along a routed path (display)."""
    return sum(
        physical_edges[edge_key(path[index], path[index + 1])].distance_miles
        for index in range(len(path) - 1)
    )


def select_core_backbone_pairs(
    core_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    min_degree: int = 3,
    required_pairs: frozenset[tuple[str, str]] = frozenset(),
) -> list[tuple[str, str]] | None:
    """Choose which core pairs get a logical backbone link.

    The result is a minimum-mileage subgraph of the full mesh in which every core
    keeps at least ``min_degree`` backbone neighbors (clamped to ``len(core_ids) -
    1`` when there are too few cores to reach it) while staying 2-edge-connected,
    so the cores remain mutually reachable after any single backbone link fails.
    The longest links are dropped first -- but only when both endpoints stay at or
    above the floor and the backbone survives the removal -- so the result need not
    be a full mesh. Any pair in ``required_pairs`` (an operator-forced core-core
    link) is never dropped. Returns ``None`` if some core pair is unreachable over
    the carrier graph (the cores do not full-mesh).
    """
    ids = set(core_ids)
    weight: dict[tuple[str, str], float] = {}
    for left, right in itertools.combinations(core_ids, 2):
        distance = all_distances[left].get(right, math.inf)
        if not math.isfinite(distance):
            return None
        weight[edge_key(left, right)] = distance
    selected = set(weight)
    floor = min(min_degree, len(ids) - 1)

    def degree(node: str) -> int:
        return sum(1 for pair in selected if node in pair)

    # Each mesh pair is visited once, longest first; drop it only when both
    # endpoints stay at or above the floor and the backbone survives without it.
    # Operator-forced pairs are pinned in and never considered for removal.
    for pair in sorted(weight, key=lambda item: (-weight[item], item)):
        if pair in required_pairs:
            continue
        if degree(pair[0]) - 1 < floor or degree(pair[1]) - 1 < floor:
            continue
        if is_two_edge_connected(ids, selected - {pair}):
            selected.discard(pair)
    return sorted(selected)


@dataclass(frozen=True)
class BackboneConstraints:
    """The core-backbone selection knobs: the degree floor and any forced pairs."""

    min_degree: int = 3
    required_pairs: frozenset[tuple[str, str]] = frozenset()


def core_mesh_paths(
    core_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    all_predecessors: dict[str, dict[str, str]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    constraints: BackboneConstraints = BackboneConstraints(),
) -> list[PathUse]:
    """Route a shortest path over the selected core-to-core backbone links.

    The backbone is the minimum-mileage subgraph in which every core keeps at
    least ``constraints.min_degree`` neighbors and pins in ``required_pairs`` (see
    :func:`select_core_backbone_pairs`).
    """
    pairs = select_core_backbone_pairs(
        core_ids, all_distances, constraints.min_degree, constraints.required_pairs
    )
    if pairs is None:
        return []
    uses: list[PathUse] = []
    for left, right in pairs:
        path = reconstruct_path(left, right, all_predecessors[left])
        uses.append(
            PathUse("core_mesh", left, right, path, path_geometry_miles(path, physical_edges))
        )
    return uses
