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

from wan_designer.model import CORE_BACKBONE_MIN_DEGREE, PathUse, PhysicalEdge, edge_key
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


def _thin_to_max_degree(
    core_ids: tuple[str, ...],
    pairs: list[tuple[str, str]],
    all_distances: dict[str, dict[str, float]],
    max_degree: int,
) -> list[tuple[str, str]]:
    """Drop the longest core-core links until each core is within ``max_degree``.

    Greedy and deterministic: the highest-mileage links are removed first, but a
    link is kept whenever removing it would push either endpoint below
    :data:`CORE_BACKBONE_MIN_DEGREE` or break the backbone's 2-edge connectivity.
    The result is a minimum-mileage, 2-edge-connected thinning of the full mesh.

    Best-effort: when the floor, 2-edge connectivity, or degree parity make the cap
    unreachable, some core may still exceed ``max_degree`` -- the achieved maximum
    then surfaces in the validation report.
    """
    floor = CORE_BACKBONE_MIN_DEGREE
    ids = set(core_ids)
    edges = set(pairs)
    degree: dict[str, int] = {}
    for left, right in edges:
        degree[left] = degree.get(left, 0) + 1
        degree[right] = degree.get(right, 0) + 1
    ordered = sorted(
        edges, key=lambda pair: (all_distances[pair[0]][pair[1]], pair), reverse=True
    )
    for left, right in ordered:
        if degree[left] <= max_degree and degree[right] <= max_degree:
            continue
        if degree[left] - 1 < floor or degree[right] - 1 < floor:
            continue
        if not is_two_edge_connected(ids, edges - {(left, right)}):
            continue
        edges.discard((left, right))
        degree[left] -= 1
        degree[right] -= 1
    return sorted(edges)


def select_core_backbone_pairs(
    core_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    removed_pairs: frozenset[tuple[str, str]] = frozenset(),
    max_degree: int | None = None,
) -> list[tuple[str, str]] | None:
    """Choose which core pairs get a logical backbone link.

    The result is the full core mesh -- every pair of cores linked -- minus any
    pair in ``removed_pairs`` (an operator-pruned core-core link from
    ``etc/*.yml``). Removals are honored unconditionally, so the backbone may drop
    below a full mesh or below 2-edge connectivity at the operator's discretion.
    Returns ``None`` if some *kept* core pair is unreachable over the carrier graph
    (the cores do not full-mesh); an unreachable pair that was removed is ignored.

    When ``max_degree`` is set the surviving mesh is thinned so no core keeps more
    than that many backbone links (see :func:`_thin_to_max_degree`).
    """
    selected: list[tuple[str, str]] = []
    for left, right in itertools.combinations(core_ids, 2):
        pair = edge_key(left, right)
        if pair in removed_pairs:
            continue
        if not math.isfinite(all_distances[left].get(right, math.inf)):
            return None
        selected.append(pair)
    if max_degree is not None:
        return _thin_to_max_degree(core_ids, selected, all_distances, max_degree)
    return sorted(selected)


@dataclass(frozen=True)
class BackboneConstraints:
    """The core-backbone selection knobs: pruned core-core pairs and a degree cap."""

    removed_pairs: frozenset[tuple[str, str]] = frozenset()
    max_degree: int | None = None


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
        core_ids, all_distances, constraints.removed_pairs, constraints.max_degree
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
