"""Select and route the core-to-core backbone.

Every core links to its ``links_per_core`` nearest reachable cores, minus any
core-core pairs the operator pruned in ``etc/*.yml``. These helpers are split from
the optimizer so the backbone concern stays cohesive and the optimizer module
stays bounded.
"""

from __future__ import annotations

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
    links_per_core: int = 3,
) -> list[tuple[str, str]] | None:
    """Choose which core pairs get a logical backbone link.

    Every core links to its ``links_per_core`` nearest reachable cores (fewer when
    the core tier itself is smaller), measured over the carrier graph in
    ``all_distances``. Any pair in ``removed_pairs`` -- an operator-pruned core-core
    link from ``etc/*.yml`` -- is skipped, so the core fills that slot with its next
    nearest peer. The per-core picks are unioned, so a core chosen by a farther peer
    can end with one more link than the target.

    Returns ``None`` when some core cannot reach that many other cores -- the carrier
    graph (or an operator removal) leaves the core tier too disconnected to wire the
    backbone.
    """
    target = min(links_per_core, len(core_ids) - 1)
    selected: set[tuple[str, str]] = set()
    for core in core_ids:
        distances = all_distances[core]
        reachable = sorted(
            (
                other
                for other in core_ids
                if other != core
                and edge_key(core, other) not in removed_pairs
                and math.isfinite(distances.get(other, math.inf))
            ),
            key=lambda other, near=distances: (near[other], other),
        )
        if len(reachable) < target:
            return None
        selected.update(edge_key(core, other) for other in reachable[:target])
    return sorted(selected)


@dataclass(frozen=True)
class BackboneConstraints:
    """The core-backbone selection knobs: pruned core-core pairs and the link count."""

    removed_pairs: frozenset[tuple[str, str]] = frozenset()
    links_per_core: int = 3


def core_mesh_paths(
    core_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    all_predecessors: dict[str, dict[str, str]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    constraints: BackboneConstraints = BackboneConstraints(),
) -> list[PathUse]:
    """Route a shortest path over each core-to-core backbone link.

    The backbone wires each core to its ``constraints.links_per_core`` nearest cores,
    minus ``constraints.removed_pairs`` (see :func:`select_core_backbone_pairs`).
    """
    pairs = select_core_backbone_pairs(
        core_ids, all_distances, constraints.removed_pairs, constraints.links_per_core
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
