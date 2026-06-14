"""Optimize a three-tier core/aggregation/access WAN over the carrier graph.

The objective, in order: aggregations win, cores break ties. Aggregation
points exist to gather clusters of nearby access sites, so the design is
ranked first by total access tail mileage (tighter clusters are better),
and ties are broken by core strength (degree + compass spread + path
straightness). The search is exact -- every feasible set of cores is
tried, with all eligible PoPs as candidates (no truncation) -- so the
result is the global best, not a heuristic.

The three Sentinel bases are forced into the aggregation tier at their
co-located PoPs; access sites with no aggregation within the tail cap are
exempt from the cap and home to their nearest two regardless.
"""

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
from wan_designer.graphs import (
    dijkstra,
    node_disjoint_paths_to_cores,
    path_edge_keys,
    reconstruct_path,
)

COMPASS_OCTANTS = 8

# The Sentinel ICBM wings, forced into the aggregation tier at their PoPs.
SENTINEL_BASE_NAMES = ("Malmstrom AFB", "Minot AFB", "F.E. Warren AFB")

def unit_adjacency(
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> dict[str, list[tuple[str, float]]]:
    """Build a unit-weight adjacency map: every fiber span counts the same."""
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for left, right in physical_edges:
        adjacency.setdefault(left, []).append((right, 1.0))
        adjacency.setdefault(right, []).append((left, 1.0))
    for neighbors in adjacency.values():
        neighbors.sort()
    return adjacency

def link_bearing(origin: Node, neighbor: Node) -> float:
    """Initial compass bearing in degrees from one node toward another."""
    lat1, lat2 = math.radians(origin.lat), math.radians(neighbor.lat)
    delta_lon = math.radians(neighbor.lon - origin.lon)
    x = math.sin(delta_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(
        delta_lon
    )
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0

def link_octants(
    pop_id: str,
    adjacency: dict[str, list[tuple[str, float]]],
    pop_by_id: dict[str, Node],
) -> set[int]:
    """The distinct compass octants (of eight) the PoP's links point toward."""
    origin = pop_by_id[pop_id]
    return {
        int(((link_bearing(origin, pop_by_id[neighbor]) + 22.5) % 360.0) // 45.0)
        for neighbor, _weight in adjacency[pop_id]
    }

def node_straightness(
    pop_id: str,
    pop_by_id: dict[str, Node],
    predecessors: dict[str, str],
) -> float:
    """Mean directness to reachable PoPs: straight-line over routed geometry."""
    origin = pop_by_id[pop_id]
    ratios: list[float] = []
    for dest_id in predecessors:
        path = reconstruct_path(pop_id, dest_id, predecessors)
        routed = sum(
            haversine_miles(pop_by_id[path[index]], pop_by_id[path[index + 1]])
            for index in range(len(path) - 1)
        )
        straight = haversine_miles(origin, pop_by_id[dest_id])
        if routed > 0.0:
            ratios.append(straight / routed)
    return sum(ratios) / len(ratios) if ratios else 0.0

def core_strength(
    pop_id: str,
    inputs: DesignInputs,
    pop_by_id: dict[str, Node],
    max_degree: int,
) -> float:
    """Score a PoP's strength: reach plus spread plus straightness (~0..3)."""
    degree = len(inputs.adjacency[pop_id])
    spread = len(link_octants(pop_id, inputs.adjacency, pop_by_id))
    straight = node_straightness(pop_id, pop_by_id, inputs.all_predecessors[pop_id])
    return degree / max_degree + spread / COMPASS_OCTANTS + straight

def path_geometry_miles(
    path: tuple[str, ...],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> float:
    """Sum the per-span straight-line estimate along a routed path (display)."""
    return sum(
        physical_edges[edge_key(path[index], path[index + 1])].distance_miles
        for index in range(len(path) - 1)
    )

def aggregation_core_paths(
    aggregation_id: str,
    core_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> tuple[float, list[PathUse]]:
    """Route an aggregation to two distinct cores over node-disjoint paths."""
    total, paths = node_disjoint_paths_to_cores(adjacency, aggregation_id, core_ids, 2)
    if not paths:
        return math.inf, []
    uses = [
        PathUse(
            "aggregation_to_core",
            aggregation_id,
            path[-1],
            path,
            path_geometry_miles(path, physical_edges),
        )
        for path in paths
    ]
    return total, uses

def core_mesh_paths(
    core_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    all_predecessors: dict[str, dict[str, str]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> list[PathUse]:
    """Route a shortest path between every pair of cores (the full mesh)."""
    uses: list[PathUse] = []
    for left, right in itertools.combinations(core_ids, 2):
        distance = all_distances[left].get(right, math.inf)
        if not math.isfinite(distance):
            return []
        path = reconstruct_path(left, right, all_predecessors[left])
        uses.append(
            PathUse("core_mesh", left, right, path, path_geometry_miles(path, physical_edges))
        )
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
    strength_by_id: dict[str, float],
    cap: float | None,
) -> tuple[tuple[float, str], tuple[float, str]] | None:
    """Pick the two nearest aggregations to dual-home one access site.

    Tails are the cost; node strength only breaks ties between equally
    near aggregations. ``cap`` bounds the tail length, or is ``None`` for
    a cap-exempt (remote) site.
    """
    ranked = sorted(
        (
            (haversine_miles(access, by_id[aggregation_id]),
             -strength_by_id.get(aggregation_id, 0.0),
             aggregation_id)
            for aggregation_id in aggregation_core
        ),
        key=lambda item: item,
    )
    if cap is not None:
        ranked = [item for item in ranked if item[0] <= cap]
    ranked = ranked[: params.aggregation_candidates_per_access]
    if len(ranked) < 2:
        return None
    return ((ranked[0][0], ranked[0][2]), (ranked[1][0], ranked[1][2]))

def finalize_design(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    params: DesignParams,
    draft: _DesignDraft,
) -> Design:
    """Compute edge sets, mileage estimate, and score for a design draft."""
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
    plan: _SearchPlan,
) -> Design | None:
    """Assemble a full three-tier design for one fixed set of core PoPs.

    Returns None if the cores cannot full-mesh, a forced aggregation
    cannot dual-home to them, or some access site cannot find two
    aggregations within its tail cap.
    """
    aggregation_core = aggregation_core_map(core_ids, inputs)
    if any(forced_id not in aggregation_core for forced_id in plan.forced_aggregation_ids):
        return None
    if len(aggregation_core) < 2:
        return None

    by_id = {node.id: node for node in inputs.carrier_pops}
    access_edges: list[AccessEdge] = []
    selected: set[str] = set(plan.forced_aggregation_ids)
    for access in inputs.access_nodes:
        cap = None if access.id in plan.exempt_access_ids else params.max_access_tail_miles
        chosen = best_aggregation_pair(
            access, aggregation_core, by_id, params, plan.strength_by_id, cap
        )
        if chosen is None:
            return None
        for distance, aggregation_id in chosen:
            access_edges.append(AccessEdge(access.id, aggregation_id, distance))
            selected.add(aggregation_id)

    path_uses = core_mesh_paths(
        core_ids, inputs.all_distances, inputs.all_predecessors, inputs.physical_edges
    )
    if not path_uses:
        return None
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

    A PoP needs at least two physical links to ever be dual-homed to two
    cores, so degree-one PoPs (spurs) are excluded regardless of role.
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
    """Run Dijkstra from every Carrier PoP for reuse across core sets."""
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

@dataclass(frozen=True)
class _SearchPlan:
    """Pre-computed context shared across every candidate core set."""

    core_candidates: list[str]
    forced_aggregation_ids: frozenset[str]
    exempt_access_ids: frozenset[str]
    strength_by_id: dict[str, float]

def nearest_pop_id(access: Node, carrier_pops: list[Node]) -> str:
    """Id of the Carrier PoP nearest to an access site."""
    return min(carrier_pops, key=lambda pop: haversine_miles(access, pop)).id

def second_nearest_miles(access: Node, aggregators: list[Node]) -> float:
    """Distance to the access site's second-nearest aggregation PoP."""
    return sorted(haversine_miles(access, pop) for pop in aggregators)[1]

def search_best_design(
    inputs: DesignInputs,
    params: DesignParams,
    plan: _SearchPlan,
) -> Design:
    """Exhaustively find the best design: min total tail, then max core strength.

    Tries every combination of ``core_count`` cores; only if none is
    feasible does it grow the core set by one and try again.
    """
    for size in range(params.core_count, len(plan.core_candidates) + 1):
        best: Design | None = None
        best_key: tuple[float, float] | None = None
        for core_set in itertools.combinations(plan.core_candidates, size):
            design = build_design_for_cores(tuple(core_set), inputs, params, plan)
            if design is None:
                continue
            key = (
                round(design.metrics.access_miles, 6),
                -sum(plan.strength_by_id[core_id] for core_id in core_set),
            )
            if best_key is None or key < best_key:
                best, best_key = design, key
        if best is not None:
            return best
    raise ValueError(
        f"No feasible design with {params.core_count} or more cores"
    )

def optimize_three_tier_design(
    nodes: list[Node],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    roles: dict[str, str],
    params: DesignParams,
) -> Design:
    """Optimize a three-tier WAN over the Carrier graph for the given parameters."""
    if params.core_count < 2:
        raise ValueError("core_count (the minimum number of cores) must be at least 2")

    carrier_pops = [node for node in nodes if node.kind == "carrier_pop"]
    all_access = [node for node in nodes if node.kind != "carrier_pop"]
    adjacency = unit_adjacency(physical_edges)
    validate_pop_graph(carrier_pops, physical_edges, adjacency)
    all_distances, all_predecessors = all_pairs_shortest(carrier_pops, adjacency)
    pop_by_id = {pop.id: pop for pop in carrier_pops}

    base_access = [node for node in all_access if node.name in SENTINEL_BASE_NAMES]
    forced = frozenset(nearest_pop_id(node, carrier_pops) for node in base_access)
    absorbed = frozenset(node.id for node in base_access)
    access_nodes = [node for node in all_access if node.id not in absorbed]

    eligible_ids = compute_eligible_ids(
        carrier_pops, roles, adjacency, params.allow_roadm_aggregation
    ) | forced
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
    max_degree = max((len(adjacency[pop_id]) for pop_id in eligible_ids), default=1)
    strength_by_id = {
        pop_id: core_strength(pop_id, inputs, pop_by_id, max_degree)
        for pop_id in eligible_ids
    }
    aggregators = [pop_by_id[pop_id] for pop_id in eligible_ids]
    exempt = frozenset(
        node.id
        for node in access_nodes
        if second_nearest_miles(node, aggregators) > params.max_access_tail_miles
    )
    core_candidates = sorted(
        eligible_ids - forced, key=lambda pop_id: (-strength_by_id[pop_id], pop_id)
    )
    if len(core_candidates) < params.core_count:
        raise ValueError("Not enough reachable core candidates")

    plan = _SearchPlan(core_candidates, forced, exempt, strength_by_id)
    return search_best_design(inputs, params, plan)
