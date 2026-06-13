"""Optimize a three-tier core/aggregation/access WAN over the carrier graph."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from wan_designer.model import (
    AccessEdge,
    Design,
    DesignInputs,
    DesignMetrics,
    DesignParams,
    Node,
    PathUse,
    PhysicalEdge,
    edge_key,
    haversine_miles,
)
from wan_designer.parsing import build_adjacency
from wan_designer.graphs import (
    dijkstra,
    node_disjoint_paths_to_cores,
    path_edge_keys,
    reconstruct_path,
)
from wan_designer.validation import validate_design


def choose_core_candidates(
    access_nodes: list[Node],
    carrier_pops: list[Node],
    eligible_ids: set[str],
    all_distances: dict[str, dict[str, float]],
    limit: int,
) -> list[str]:
    """Rank eligible PoPs as core candidates by graph and access centrality."""
    by_id = {node.id: node for node in carrier_pops}
    scored: list[tuple[float, str]] = []
    for pop_id in eligible_ids:
        pop = by_id[pop_id]
        graph_distances = all_distances[pop_id]
        reachable_distances = [
            distance for node_id, distance in graph_distances.items() if node_id != pop_id
        ]
        graph_score = sum(reachable_distances) / len(reachable_distances)
        access_score = sum(
            haversine_miles(access, pop) for access in access_nodes
        ) / len(access_nodes)
        scored.append((graph_score + access_score, pop_id))
    scored.sort()
    return [pop_id for _score, pop_id in scored[:limit]]

def aggregation_core_paths(
    aggregation_id: str,
    core_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> tuple[float, list[PathUse]]:
    """Route an aggregation to two distinct cores over node-disjoint paths.

    Returns the total path distance and one ``aggregation_to_core`` PathUse per
    core, or ``(math.inf, [])`` if two node-disjoint paths to two distinct cores
    do not exist over the physical graph.
    """
    total, paths = node_disjoint_paths_to_cores(adjacency, aggregation_id, core_ids, 2)
    if not paths:
        return math.inf, []
    uses = [
        PathUse(
            "aggregation_to_core",
            aggregation_id,
            path[-1],
            path,
            sum(
                physical_edges[edge_key(path[index], path[index + 1])].distance_miles
                for index in range(len(path) - 1)
            ),
        )
        for path in paths
    ]
    return total, uses

def core_mesh_paths(
    core_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    all_predecessors: dict[str, dict[str, str]],
) -> list[PathUse]:
    """Route a shortest path between every pair of cores (the full mesh)."""
    uses: list[PathUse] = []
    for left, right in itertools.combinations(core_ids, 2):
        distance = all_distances[left].get(right, math.inf)
        if not math.isfinite(distance):
            return []
        path = reconstruct_path(left, right, all_predecessors[left])
        uses.append(PathUse("core_mesh", left, right, path, distance))
    return uses

@dataclass
class _DesignDraft:
    access_edges: list[AccessEdge]
    selected_aggregation_ids: set[str]
    path_uses: list[PathUse]

def aggregation_core_map(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
) -> dict[str, tuple[float, list[PathUse]]]:
    """Map each eligible aggregation to its node-disjoint routing to two cores."""
    allowed = sorted(inputs.eligible_aggregation_ids - set(core_ids))
    feasible: dict[str, tuple[float, list[PathUse]]] = {}
    for aggregation_id in allowed:
        cost, paths = aggregation_core_paths(
            aggregation_id, core_ids, inputs.adjacency, inputs.physical_edges
        )
        if math.isfinite(cost):
            feasible[aggregation_id] = (cost, paths)
    return feasible

def best_aggregation_pair(
    access: Node,
    aggregation_core: dict[str, tuple[float, list[PathUse]]],
    by_id: dict[str, Node],
    params: DesignParams,
) -> tuple[tuple[float, str], tuple[float, str]] | None:
    """Pick the cheapest pair of aggregations to dual-home one access node."""
    ranked = sorted(
        (
            (haversine_miles(access, by_id[aggregation_id]), aggregation_id)
            for aggregation_id in aggregation_core
        ),
        key=lambda item: (item[0], item[1]),
    )[: params.aggregation_candidates_per_access]
    best_cost = math.inf
    chosen: tuple[tuple[float, str], tuple[float, str]] | None = None
    for left, right in itertools.combinations(ranked, 2):
        pair_cost = (
            left[0]
            + right[0]
            + params.upper_tier_weight
            * (aggregation_core[left[1]][0] + aggregation_core[right[1]][0])
        )
        if pair_cost < best_cost:
            best_cost = pair_cost
            chosen = (left, right)
    return chosen

def finalize_design(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    params: DesignParams,
    draft: _DesignDraft,
) -> Design:
    """Compute edge sets, mileage, and score for a completed design draft."""
    physical_edge_keys: set[tuple[str, str]] = set()
    for path_use in draft.path_uses:
        physical_edge_keys.update(path_edge_keys(path_use.path))

    access_miles = sum(edge.distance_miles for edge in draft.access_edges)
    physical_miles = sum(
        inputs.physical_edges[key].distance_miles for key in physical_edge_keys
    )
    score = (
        access_miles
        + physical_miles
        + params.aggregation_penalty_miles * len(draft.selected_aggregation_ids)
    )
    carrier_on_paths = {node_id for use in draft.path_uses for node_id in use.path}
    transit_ids = tuple(
        sorted(carrier_on_paths - set(core_ids) - draft.selected_aggregation_ids)
    )
    return Design(
        core_ids=core_ids,
        aggregation_ids=tuple(sorted(draft.selected_aggregation_ids)),
        transit_ids=transit_ids,
        access_edges=draft.access_edges,
        physical_edge_keys=physical_edge_keys,
        path_uses=draft.path_uses,
        metrics=DesignMetrics(score, access_miles, physical_miles),
    )

def build_design_for_cores(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    params: DesignParams,
) -> Design | None:
    """Assemble a full three-tier design for one fixed set of core PoPs."""
    aggregation_core = aggregation_core_map(core_ids, inputs)
    if len(aggregation_core) < 2:
        return None

    by_id = {node.id: node for node in inputs.carrier_pops}
    access_edges: list[AccessEdge] = []
    selected: set[str] = set()
    for access in inputs.access_nodes:
        chosen = best_aggregation_pair(access, aggregation_core, by_id, params)
        if chosen is None:
            return None
        for distance, aggregation_id in chosen:
            access_edges.append(AccessEdge(access.id, aggregation_id, distance))
            selected.add(aggregation_id)

    path_uses = core_mesh_paths(core_ids, inputs.all_distances, inputs.all_predecessors)
    for aggregation_id in sorted(selected):
        path_uses.extend(aggregation_core[aggregation_id][1])

    draft = _DesignDraft(access_edges, selected, path_uses)
    return finalize_design(core_ids, inputs, params, draft)

def compute_eligible_ids(
    carrier_pops: list[Node],
    roles: dict[str, str],
    adjacency: dict[str, list[tuple[str, float]]],
    allow_roadm_aggregation: bool,
) -> set[str]:
    """Carrier PoPs that may serve as core or aggregation nodes.

    A PoP needs at least two physical links to ever be dual-homed to two cores,
    so degree-one PoPs (spurs) are excluded regardless of their mapbook role.
    """
    return {
        pop.id
        for pop in carrier_pops
        if (allow_roadm_aggregation or roles.get(pop.id, "aggregator") == "aggregator")
        and len(adjacency.get(pop.id, [])) >= 2
    }

def all_pairs_shortest(
    carrier_pops: list[Node],
    adjacency: dict[str, list[tuple[str, float]]],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, str]]]:
    """Run Dijkstra from every Carrier PoP for reuse across core combinations."""
    all_distances: dict[str, dict[str, float]] = {}
    all_predecessors: dict[str, dict[str, str]] = {}
    for pop in carrier_pops:
        all_distances[pop.id], all_predecessors[pop.id] = dijkstra(adjacency, pop.id)
    return all_distances, all_predecessors

def validate_pop_graph(
    carrier_pops: list[Node],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    adjacency: dict[str, list[tuple[str, float]]],
) -> None:
    """Raise if the physical edge graph and Carrier PoP set are inconsistent."""
    pop_ids = {pop.id for pop in carrier_pops}
    physical_node_ids = {node_id for edge in physical_edges for node_id in edge}
    if not pop_ids.issuperset(physical_node_ids):
        raise ValueError("Physical edge graph references unknown Carrier PoP IDs")
    missing_pops = sorted(pop_ids - set(adjacency))
    if missing_pops:
        names = ", ".join(node.name for node in carrier_pops if node.id in missing_pops)
        raise ValueError(f"Carrier PoPs missing from physical edge graph: {names}")

def cores_too_close(
    core_ids: tuple[str, ...],
    pop_by_id: dict[str, Node],
    min_separation_miles: float,
) -> bool:
    """True if any pair of candidate cores is closer than the separation floor."""
    return any(
        haversine_miles(pop_by_id[left], pop_by_id[right]) < min_separation_miles
        for left, right in itertools.combinations(core_ids, 2)
    )

def scored_design(nodes: list[Node], design: Design) -> Design:
    """Add large penalties for any violated hard requirement to the score."""
    validation = validate_design(nodes, design)
    penalties = (
        validation["min_distinct_neighbor_degree"] < 2,
        not validation["connected"],
        not validation["aggregations_dual_homed_to_cores"],
        not validation["cores_full_mesh"],
    )
    design.metrics.score += 1_000_000.0 * sum(1 for failed in penalties if failed)
    return design

def search_best_design(
    nodes: list[Node],
    inputs: DesignInputs,
    params: DesignParams,
    core_candidates: list[str],
) -> Design:
    """Search core combinations for the lowest-scoring feasible design."""
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    best: Design | None = None
    checked = 0
    for core_ids in itertools.combinations(core_candidates, params.core_count):
        if cores_too_close(core_ids, pop_by_id, params.min_core_separation_miles):
            continue
        checked += 1
        design = build_design_for_cores(tuple(core_ids), inputs, params)
        if design is None:
            continue
        design = scored_design(nodes, design)
        if best is None or design.metrics.score < best.metrics.score:
            best = design
    if best is None:
        raise ValueError(f"No feasible three-tier design found after {checked} core sets")
    return best

def optimize_three_tier_design(
    nodes: list[Node],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    roles: dict[str, str],
    params: DesignParams,
) -> Design:
    """Optimize a three-tier WAN over the Carrier graph for the given parameters."""
    if params.core_count < 2 or params.core_count > 3:
        raise ValueError("core_count must be 2 or 3")

    access_nodes = [node for node in nodes if node.kind != "carrier_pop"]
    carrier_pops = [node for node in nodes if node.kind == "carrier_pop"]
    adjacency = build_adjacency(physical_edges)
    validate_pop_graph(carrier_pops, physical_edges, adjacency)
    all_distances, all_predecessors = all_pairs_shortest(carrier_pops, adjacency)

    eligible_ids = compute_eligible_ids(
        carrier_pops, roles, adjacency, params.allow_roadm_aggregation
    )
    if len(eligible_ids) < max(2, params.core_count):
        raise ValueError("Not enough eligible Carrier aggregation/core PoPs")

    inputs = DesignInputs(
        access_nodes=access_nodes,
        carrier_pops=carrier_pops,
        physical_edges=physical_edges,
        eligible_aggregation_ids=eligible_ids,
        adjacency=adjacency,
        all_distances=all_distances,
        all_predecessors=all_predecessors,
    )
    core_candidates = choose_core_candidates(
        access_nodes, carrier_pops, eligible_ids, all_distances, params.core_candidate_limit
    )
    if len(core_candidates) < params.core_count:
        raise ValueError("Not enough reachable core candidates")

    return search_best_design(nodes, inputs, params, core_candidates)
