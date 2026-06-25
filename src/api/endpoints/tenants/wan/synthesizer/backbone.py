"""Select and route the backbone-to-backbone mesh.

Every backbone node links to its ``mesh_degree`` nearest reachable backbone nodes,
minus any backbone-backbone pairs the operator pruned in ``etc/*.yml``. These
helpers are split from the synthesizer so the backbone concern stays cohesive and
the synthesizer module stays bounded.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from synthesizer.input_graph import PhysicalEdge, edge_key
from synthesizer.graphs import reconstruct_path
from synthesizer.model import PathUse


def path_geometry_miles(
    path: tuple[str, ...],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> float:
    """Sum the per-span straight-line estimate along a routed path (display)."""
    return sum(
        physical_edges[edge_key(path[index], path[index + 1])].distance_miles
        for index in range(len(path) - 1)
    )


def select_backbone_mesh_pairs(
    backbone_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    removed_pairs: frozenset[tuple[str, str]] = frozenset(),
    mesh_degree: int = 3,
) -> list[tuple[str, str]]:
    """Choose which backbone pairs get a logical mesh link.

    Every backbone node links to its ``mesh_degree`` nearest reachable backbone nodes
    (fewer when the backbone itself is smaller), measured over the carrier graph in
    ``all_distances``. Any pair in ``removed_pairs`` -- an operator-pruned
    backbone-backbone link from ``etc/*.yml`` -- is skipped, so the node fills that
    slot with its next nearest peer. The per-node picks are unioned, so a node chosen
    by a farther peer can end with one more link than the target.

    A node left with fewer reachable, non-removed peers than the target -- because the
    operator pruned its links or the carrier graph cannot reach them -- wires to every
    peer it can and no more. Thinning one node below the target therefore costs only
    that node's missing links, never the rest of the backbone, so an operator may
    deliberately isolate a node without blanking the whole mesh.
    """
    target = min(mesh_degree, len(backbone_ids) - 1)
    selected: set[tuple[str, str]] = set()
    for node in backbone_ids:
        distances = all_distances[node]
        nearest = sorted(
            (distances[other], other)
            for other in backbone_ids
            if other != node
            and edge_key(node, other) not in removed_pairs
            and math.isfinite(distances.get(other, math.inf))
        )
        selected.update(edge_key(node, other) for _distance, other in nearest[:target])
    return sorted(selected)


@dataclass(frozen=True)
class BackboneConstraints:
    """The backbone-mesh selection knobs: pruned backbone pairs and the link count."""

    removed_pairs: frozenset[tuple[str, str]] = frozenset()
    mesh_degree: int = 3


def backbone_mesh_paths(
    backbone_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    all_predecessors: dict[str, dict[str, str]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    constraints: BackboneConstraints = BackboneConstraints(),
) -> list[PathUse]:
    """Route a shortest path over each backbone-to-backbone mesh link.

    The mesh wires each backbone node to its ``constraints.mesh_degree`` nearest
    nodes, minus ``constraints.removed_pairs`` (see :func:`select_backbone_mesh_pairs`).
    """
    pairs = select_backbone_mesh_pairs(
        backbone_ids, all_distances, constraints.removed_pairs, constraints.mesh_degree
    )
    uses: list[PathUse] = []
    for left, right in pairs:
        path = reconstruct_path(left, right, all_predecessors[left])
        uses.append(
            PathUse("backbone_mesh", left, right, path, path_geometry_miles(path, physical_edges))
        )
    return uses
