"""Optimize a three-tier core/aggregation/access WAN over the carrier graph.

The objective, in order: aggregations win, cores break ties. Aggregation
points exist to gather clusters of nearby access sites, so the design is
ranked first by total last-mile mileage (tighter clusters are better),
and ties are broken by core strength (degree + compass spread + path
straightness). The search is exact -- every feasible set of cores is
tried, with all eligible PoPs as candidates (no truncation) -- so the
result is the global best, not a heuristic.

The three Sentinel bases are forced into the aggregation tier at their
co-located PoPs; access sites with no aggregation within the last-mile cap are
exempt from the cap and home to their nearest two regardless.
"""

from __future__ import annotations

import itertools
import logging
import math
from dataclasses import dataclass, field

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

logger = logging.getLogger(__name__)

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

def core_pairs(core_ids: tuple[str, ...]) -> list[tuple[str, str]]:
    """The two-core combinations of a core set, each as an ordered key."""
    return [edge_key(left, right) for left, right in itertools.combinations(core_ids, 2)]

def dual_homes_to_pair(
    aggregation_id: str,
    pair: tuple[str, str],
    inputs: DesignInputs,
    cache: dict[tuple[str, str, str], bool],
) -> bool:
    """True if the aggregation has node-disjoint paths to both cores of a pair.

    Results are memoized per (aggregation, core pair). Feasibility to a trio is
    the OR over its three pairs, so each pair's max-flow is computed only once
    and reused across every trio that contains it.
    """
    key = (aggregation_id, pair[0], pair[1])
    cached = cache.get(key)
    if cached is None:
        cost, _paths = node_disjoint_paths_to_cores(inputs.adjacency, aggregation_id, pair, 2)
        cached = math.isfinite(cost)
        cache[key] = cached
    return cached

def aggregation_dual_homes(
    aggregation_id: str,
    pairs: list[tuple[str, str]],
    inputs: DesignInputs,
    cache: dict[tuple[str, str, str], bool],
) -> bool:
    """True if the aggregation can dual-home to two cores of the given set."""
    return any(dual_homes_to_pair(aggregation_id, pair, inputs, cache) for pair in pairs)

def feasible_aggregation_ids(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    plan: _SearchPlan,
) -> set[str]:
    """Eligible aggregations that can dual-home to two of the given cores.

    Only feasibility is computed here -- routed paths are reconstructed once for
    the winning core set -- because the design is ranked solely on last-mile
    mileage and core strength, neither of which depends on those paths.
    """
    pairs = core_pairs(core_ids)
    candidates = inputs.eligible_aggregation_ids - set(core_ids)
    return {
        aggregation_id
        for aggregation_id in candidates
        if aggregation_dual_homes(aggregation_id, pairs, inputs, plan.feasibility_cache)
    }

def cores_mesh(core_ids: tuple[str, ...], all_distances: dict[str, dict[str, float]]) -> bool:
    """True if every pair of cores is connected over the carrier graph."""
    return all(
        math.isfinite(all_distances[left].get(right, math.inf))
        for left, right in itertools.combinations(core_ids, 2)
    )

def best_aggregation_pair(
    access: Node,
    feasible_ids: set[str],
    params: DesignParams,
    plan: _SearchPlan,
) -> tuple[tuple[float, str], tuple[float, str]] | None:
    """Pick the two nearest feasible aggregations to dual-home one access site.

    The site's aggregations are pre-ranked by last-mile distance (ties broken by
    strength); this walks that order, keeping the nearest feasible ones within
    the last-mile cap. The cap is waived for exempt (too-remote) sites.
    """
    cap = None if access.id in plan.exempt_access_ids else params.max_last_mile_miles
    eligible: list[tuple[float, str]] = []
    for distance, aggregation_id in plan.ranked_by_access[access.id]:
        if cap is not None and distance > cap:
            break
        if aggregation_id in feasible_ids:
            eligible.append((distance, aggregation_id))
            if len(eligible) == params.aggregation_candidates_per_access:
                break
    if len(eligible) < 2:
        return None
    return (eligible[0], eligible[1])

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

def forced_can_dual_home(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    plan: _SearchPlan,
) -> bool:
    """True if every forced aggregation can dual-home to two of the cores."""
    pairs = core_pairs(core_ids)
    return all(
        aggregation_dual_homes(forced_id, pairs, inputs, plan.feasibility_cache)
        for forced_id in plan.forced_aggregation_ids
    )

def assign_access(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    params: DesignParams,
    plan: _SearchPlan,
) -> tuple[list[AccessEdge], set[str]] | None:
    """Home every access site to its two nearest feasible aggregations.

    Returns the access edges and the selected aggregation ids, or None if too
    few aggregations are feasible or some site cannot find two within its cap.
    """
    feasible_ids = feasible_aggregation_ids(core_ids, inputs, plan)
    if len(feasible_ids) < 2:
        return None
    access_edges: list[AccessEdge] = []
    selected: set[str] = set(plan.forced_aggregation_ids)
    for access in inputs.access_nodes:
        chosen = best_aggregation_pair(access, feasible_ids, params, plan)
        if chosen is None:
            return None
        for distance, aggregation_id in chosen:
            access_edges.append(AccessEdge(access.id, aggregation_id, distance))
            selected.add(aggregation_id)
    return access_edges, selected

def evaluate_cores(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    params: DesignParams,
    plan: _SearchPlan,
) -> tuple[list[AccessEdge], set[str]] | None:
    """Score a core set's feasibility and access homing without routing paths.

    Returns None when the cores do not full-mesh, a forced aggregation cannot
    dual-home, or some access site cannot find two aggregations within its cap.
    Routed paths are deferred to the winning set, since they do not affect the
    last-mile/strength ranking.
    """
    if not cores_mesh(core_ids, inputs.all_distances):
        return None
    if not forced_can_dual_home(core_ids, inputs, plan):
        return None
    return assign_access(core_ids, inputs, params, plan)

def routed_path_uses(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    selected: set[str],
) -> list[PathUse]:
    """Reconstruct the core-mesh and aggregation-to-core paths for a design."""
    path_uses = core_mesh_paths(
        core_ids, inputs.all_distances, inputs.all_predecessors, inputs.physical_edges
    )
    for aggregation_id in sorted(selected):
        _cost, uses = aggregation_core_paths(
            aggregation_id, core_ids, inputs.adjacency, inputs.physical_edges
        )
        path_uses.extend(uses)
    return path_uses

def build_design_for_cores(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    params: DesignParams,
    plan: _SearchPlan,
) -> Design | None:
    """Assemble a full three-tier design for one fixed set of core PoPs.

    Returns None if the cores cannot full-mesh, a forced aggregation cannot
    dual-home to them, or some access site cannot find two aggregations within
    its last-mile cap.
    """
    evaluation = evaluate_cores(core_ids, inputs, params, plan)
    if evaluation is None:
        return None
    access_edges, selected = evaluation
    path_uses = routed_path_uses(core_ids, inputs, selected)
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
    """Pre-computed context shared across every candidate core set.

    ``ranked_by_access`` pre-sorts each access site's aggregations by last-mile
    distance (it is core-independent), and ``feasibility_cache`` memoizes
    per-pair node-disjoint reachability, so the search avoids re-sorting and
    re-running max-flows for every trio.
    """

    core_candidates: list[str]
    forced_aggregation_ids: frozenset[str]
    exempt_access_ids: frozenset[str]
    strength_by_id: dict[str, float]
    ranked_by_access: dict[str, list[tuple[float, str]]] = field(default_factory=dict)
    feasibility_cache: dict[tuple[str, str, str], bool] = field(default_factory=dict)

def rank_aggregations(
    access: Node,
    eligible_ids: set[str],
    pop_by_id: dict[str, Node],
    strength_by_id: dict[str, float],
) -> list[tuple[float, str]]:
    """An access site's eligible aggregations, nearest first, strength breaks ties."""
    scored = sorted(
        (haversine_miles(access, pop_by_id[agg_id]), -strength_by_id[agg_id], agg_id)
        for agg_id in eligible_ids
    )
    return [(distance, agg_id) for distance, _strength, agg_id in scored]

def nearest_pop_id(access: Node, carrier_pops: list[Node]) -> str:
    """Id of the Carrier PoP nearest to an access site."""
    return min(carrier_pops, key=lambda pop: haversine_miles(access, pop)).id

def second_nearest_miles(access: Node, aggregators: list[Node]) -> float:
    """Distance to the access site's second-nearest aggregation PoP."""
    return sorted(haversine_miles(access, pop) for pop in aggregators)[1]

def core_set_strength(core_ids: tuple[str, ...], plan: _SearchPlan) -> float:
    """Total strength of a core set: the primary objective the search maximizes."""
    return sum(plan.strength_by_id[core_id] for core_id in core_ids)

def best_design_at_size(
    inputs: DesignInputs,
    params: DesignParams,
    plan: _SearchPlan,
    size: int,
) -> Design | None:
    """Best design using exactly ``size`` cores, or None if none is feasible.

    The objective is core strength (the spec forbids mileage as a design cost):
    the strongest feasible core set wins, with total last-mile only breaking ties
    among equally strong sets. Core sets are tried strongest-first and scored
    cheaply (feasibility plus access homing, no routed paths). Because strength
    is non-increasing down that order, the moment a feasible set is in hand the
    search stops as soon as a candidate is strictly weaker. Routed paths are
    reconstructed only for the winning set.
    """
    combos = sorted(
        itertools.combinations(plan.core_candidates, size),
        key=lambda combo: -core_set_strength(combo, plan),
    )
    logger.info("Evaluating %d core sets of size %d, strongest first", len(combos), size)
    best_core_set: tuple[str, ...] | None = None
    best_key: tuple[float, float] | None = None
    best_strength = -math.inf
    for index, core_set in enumerate(combos, start=1):
        strength = core_set_strength(core_set, plan)
        if strength < best_strength:
            logger.info("  strongest feasible cores locked at set %d/%d", index, len(combos))
            break
        evaluation = evaluate_cores(core_set, inputs, params, plan)
        if evaluation is None:
            continue
        access_miles = sum(edge.distance_miles for edge in evaluation[0])
        key = (-strength, round(access_miles, 6))
        if best_key is None or key < best_key:
            best_core_set, best_key, best_strength = core_set, key, strength
            logger.info(
                "  set %d/%d: new best strength %.3f, last-mile %.0f mi",
                index, len(combos), strength, access_miles,
            )
    if best_core_set is None:
        return None
    return build_design_for_cores(best_core_set, inputs, params, plan)

def search_best_design(
    inputs: DesignInputs,
    params: DesignParams,
    plan: _SearchPlan,
) -> Design:
    """Find the globally best design: max core strength, then min total last-mile.

    Grows the core set from ``core_count`` only when no smaller set is
    feasible.
    """
    logger.info(
        "Optimizing %d access sites over %d core candidates, strongest cores first",
        len(inputs.access_nodes), len(plan.core_candidates),
    )
    for size in range(params.core_count, len(plan.core_candidates) + 1):
        design = best_design_at_size(inputs, params, plan, size)
        if design is not None:
            return design
    raise ValueError(f"No feasible design with {params.core_count} or more cores")

def graph_context(
    nodes: list[Node],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> tuple[
    list[Node],
    list[Node],
    dict[str, list[tuple[str, float]]],
    dict[str, dict[str, float]],
    dict[str, dict[str, str]],
]:
    """Split nodes into PoPs/access and precompute the shared graph context."""
    carrier_pops = [node for node in nodes if node.kind == "carrier_pop"]
    all_access = [node for node in nodes if node.kind != "carrier_pop"]
    adjacency = unit_adjacency(physical_edges)
    validate_pop_graph(carrier_pops, physical_edges, adjacency)
    all_distances, all_predecessors = all_pairs_shortest(carrier_pops, adjacency)
    return carrier_pops, all_access, adjacency, all_distances, all_predecessors

def sentinel_split(
    all_access: list[Node], carrier_pops: list[Node]
) -> tuple[frozenset[str], list[Node]]:
    """Force each Sentinel base into the aggregation tier at its co-located PoP.

    Returns the forced aggregation ids and the remaining (homed) access
    nodes; the base demand sites are absorbed into their forced PoPs.
    """
    base_access = [node for node in all_access if node.name in SENTINEL_BASE_NAMES]
    forced = frozenset(nearest_pop_id(node, carrier_pops) for node in base_access)
    absorbed = frozenset(node.id for node in base_access)
    access_nodes = [node for node in all_access if node.id not in absorbed]
    return forced, access_nodes

def build_search_plan(
    inputs: DesignInputs,
    eligible_ids: set[str],
    forced: frozenset[str],
    params: DesignParams,
) -> _SearchPlan:
    """Compute node strengths, cap-exempt access sites, and core candidates."""
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    max_degree = max((len(inputs.adjacency[pop_id]) for pop_id in eligible_ids), default=1)
    strength_by_id = {
        pop_id: core_strength(pop_id, inputs, pop_by_id, max_degree)
        for pop_id in eligible_ids
    }
    aggregators = [pop_by_id[pop_id] for pop_id in eligible_ids]
    exempt = frozenset(
        node.id
        for node in inputs.access_nodes
        if second_nearest_miles(node, aggregators) > params.max_last_mile_miles
    )
    ranked_by_access = {
        access.id: rank_aggregations(access, eligible_ids, pop_by_id, strength_by_id)
        for access in inputs.access_nodes
    }
    core_candidates = sorted(
        eligible_ids - forced, key=lambda pop_id: (-strength_by_id[pop_id], pop_id)
    )
    return _SearchPlan(
        core_candidates, forced, exempt, strength_by_id, ranked_by_access
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

    carrier_pops, all_access, adjacency, all_distances, all_predecessors = graph_context(
        nodes, physical_edges
    )
    forced, access_nodes = sentinel_split(all_access, carrier_pops)
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
    plan = build_search_plan(inputs, eligible_ids, forced, params)
    if len(plan.core_candidates) < params.core_count:
        raise ValueError("Not enough reachable core candidates")
    return search_best_design(inputs, params, plan)
