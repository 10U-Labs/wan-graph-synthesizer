"""Select and route the core-to-core backbone.

The backbone is the full core mesh -- every core links to every other -- minus any
core-core pairs the operator pruned in ``etc/*.yml``. These helpers are split from
the optimizer so the backbone concern stays cohesive and the optimizer module
stays bounded.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from wan_designer.model import PathUse, PhysicalEdge, edge_key
from wan_designer.graphs import reconstruct_path


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
    removed_pairs: frozenset[tuple[str, str]] = frozenset(),
) -> list[tuple[str, str]] | None:
    """Choose which core pairs get a logical backbone link.

    The result is the full core mesh -- every pair of cores linked -- minus any
    pair in ``removed_pairs`` (an operator-pruned core-core link from
    ``etc/*.yml``). Removals are honored unconditionally, so the backbone may drop
    below a full mesh or below 2-edge connectivity at the operator's discretion.
    Returns ``None`` if some *kept* core pair is unreachable over the carrier graph
    (the cores do not full-mesh); an unreachable pair that was removed is ignored.
    """
    selected: list[tuple[str, str]] = []
    for left, right in itertools.combinations(core_ids, 2):
        pair = edge_key(left, right)
        if pair in removed_pairs:
            continue
        if not math.isfinite(all_distances[left].get(right, math.inf)):
            return None
        selected.append(pair)
    return sorted(selected)


@dataclass(frozen=True)
class BackboneConstraints:
    """The core-backbone selection knobs: the operator-pruned core-core pairs."""

    removed_pairs: frozenset[tuple[str, str]] = frozenset()


def core_mesh_paths(
    core_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    all_predecessors: dict[str, dict[str, str]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    constraints: BackboneConstraints = BackboneConstraints(),
) -> list[PathUse]:
    """Route a shortest path over each core-to-core backbone link.

    The backbone is the full core mesh minus ``constraints.removed_pairs`` (see
    :func:`select_core_backbone_pairs`).
    """
    pairs = select_core_backbone_pairs(
        core_ids, all_distances, constraints.removed_pairs
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
