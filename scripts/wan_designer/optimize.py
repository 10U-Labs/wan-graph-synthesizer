"""Optimize a three-tier core/aggregation/access WAN over the carrier graph.

Cores are chosen for strength, not mileage (the source mapbook has no
distances): each core's strength is its degree plus compass spread plus path
straightness, and the strongest feasible set of the configured ``core_count``
wins, with total last-mile only breaking ties.

Access sites with no aggregation within the last-mile cap are exempt from the cap
and home to their nearest two regardless.

On top of the algorithm, the operator may pin roles by PoP name (``RoleOverrides``,
resolved by ``apply_role_overrides``): force a PoP to be a core, force it to be an
aggregation, or exclude it from every selected role. A PoP forced as both a core
and an aggregation is co-located: it is split into a distinct ``CORE`` vertex and a
co-located ``AGGR`` vertex that share coordinates and a zero-mile in-facility
cross-connect, with the core's fiber duplicated onto the aggregation's distinct
hardware stack so the aggregation reaches its own co-located core as one of its two
vertex-disjoint cores and a remote core as the other (see ``apply_role_overrides``).
"""

from __future__ import annotations

import itertools
import logging
import math
import os
from dataclasses import dataclass, field

from wan_designer.model import (
    AccessEdge,
    Design,
    DesignInputs,
    DesignMetrics,
    DesignParams,
    Vertex,
    PathUse,
    PhysicalEdge,
    RoleOverrides,
    edge_key,
    haversine_miles,
    is_carrier_pop,
)
from wan_designer.graphs import (
    dijkstra,
    vertex_disjoint_paths_to_cores,
    path_edge_keys,
    reconstruct_path,
)
from wan_designer.clustering import cluster_access_vertices

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

def link_bearing(origin: Vertex, neighbor: Vertex) -> float:
    """Initial compass bearing in degrees from one vertex toward another."""
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
    pop_by_id: dict[str, Vertex],
) -> set[int]:
    """The distinct compass octants (of eight) the PoP's links point toward."""
    origin = pop_by_id[pop_id]
    return {
        int(((link_bearing(origin, pop_by_id[neighbor]) + 22.5) % 360.0) // 45.0)
        for neighbor, _weight in adjacency[pop_id]
    }

def vertex_straightness(
    pop_id: str,
    pop_by_id: dict[str, Vertex],
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
    pop_by_id: dict[str, Vertex],
    max_degree: int,
    compass_octants: int,
) -> float:
    """Score a PoP's strength: reach plus spread plus straightness (~0..3)."""
    degree = len(inputs.adjacency[pop_id])
    spread = len(link_octants(pop_id, inputs.adjacency, pop_by_id))
    straight = vertex_straightness(pop_id, pop_by_id, inputs.all_predecessors[pop_id])
    return degree / max_degree + spread / compass_octants + straight

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
    """Route an aggregation to two distinct cores over vertex-disjoint paths."""
    total, paths = vertex_disjoint_paths_to_cores(adjacency, aggregation_id, core_ids, 2)
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
    """True if the aggregation has vertex-disjoint paths to both cores of a pair.

    Results are memoized per (aggregation, core pair). Feasibility to a trio is
    the OR over its three pairs, so each pair's max-flow is computed only once
    and reused across every trio that contains it.
    """
    key = (aggregation_id, pair[0], pair[1])
    cached = cache.get(key)
    if cached is None:
        cost, _paths = vertex_disjoint_paths_to_cores(inputs.adjacency, aggregation_id, pair, 2)
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

def cluster_diameter(members: list[Vertex]) -> float:
    """The farthest great-circle distance between any two members of a cluster."""
    return max(
        (haversine_miles(left, right) for left in members for right in members),
        default=0.0,
    )

def cluster_local_heads(
    members: list[Vertex],
    feasible_ids: set[str],
    selected: set[str],
    pop_by_id: dict[str, Vertex],
) -> list[str]:
    """Up to two distinct feasible PoPs local to a cluster, its heads.

    A PoP is local when it sits within the cluster's own extent -- its diameter,
    the farthest distance between two members -- of at least one member, so a
    head is never much farther from the cluster than the cluster is wide. Of the
    locals, an already-selected facility (a forced aggregation, or a head placed
    for an earlier cluster) is always preferred over a new build, so a cluster
    sitting on a pin reuses it rather than standing up a redundant neighbor; the
    cluster still opens a new head for any remaining slot. Within each group the
    PoPs nearest the cluster as a whole (least total distance to its members)
    win. A distant PoP (Boise, ~243 mi from the nearest Utah member, well beyond
    that cluster's ~100 mi extent) is never built as the cluster's head; that
    cluster's second home comes from reuse.
    """
    diameter = cluster_diameter(members)
    reuse: list[tuple[float, str]] = []
    build: list[tuple[float, str]] = []
    for aggregation_id in feasible_ids:
        pop = pop_by_id[aggregation_id]
        if min(haversine_miles(member, pop) for member in members) <= diameter:
            total = sum(haversine_miles(member, pop) for member in members)
            (reuse if aggregation_id in selected else build).append((total, aggregation_id))
    reuse.sort()
    build.sort()
    return [aggregation_id for _total, aggregation_id in (reuse + build)[:2]]

def complete_homes(
    access: Vertex,
    current: list[str],
    selected: set[str],
    feasible_ids: set[str],
    pop_by_id: dict[str, Vertex],
) -> list[str]:
    """Fill an access vertex out toward two homes, preferring reuse over a build.

    Existing facilities (cluster heads already placed, forced bases) are reused
    first; a new aggregation is opened only when fewer than two existing
    facilities are reachable -- the last resort for a lone vertex or a synthetic
    graph with no clusters. With two or more feasible aggregations available this
    always reaches two; it can return fewer only when the graph cannot offer two.
    """
    homes = list(current)
    for source in (selected, feasible_ids):
        for _distance, facility in sorted(
            (haversine_miles(access, pop_by_id[facility]), facility)
            for facility in source
            if facility not in homes
        ):
            if len(homes) >= 2:
                break
            homes.append(facility)
    return homes

def finalize_design(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
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
    score = access_miles + physical_miles
    carrier_on_paths = {vertex_id for use in draft.path_uses for vertex_id in use.path}
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
    plan: _SearchPlan,
) -> tuple[list[AccessEdge], set[str]] | None:
    """Home every access vertex by clustering: cluster heads first, then reuse.

    Aggregations are placed as the heads of dense access-vertex clusters (two
    distinct local PoPs each). Every vertex then dual-homes to two facilities,
    completing any gap (a cluster with one local head, or a sparse lone vertex) by
    reusing an existing facility rather than building a redundant one. Returns
    the access edges and selected aggregation ids, or None if some vertex cannot
    reach two facilities.
    """
    feasible_ids = feasible_aggregation_ids(core_ids, inputs, plan)
    if len(feasible_ids) < 2:
        return None
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    access_by_id = {access.id: access for access in inputs.access_vertices}
    selected: set[str] = set(plan.forced_aggregation_ids)
    homes: dict[str, list[str]] = {}

    # Pass 1: stand up each cluster's local aggregation heads. This places the
    # facilities only -- where to build -- and never pins a member to them.
    # Homing is left to pass 2 so a peripheral member of a sprawling cluster
    # homes to whichever selected facility is actually nearest, not to a distant
    # common head chosen for the cluster as a whole.
    for members in plan.clusters:
        member_vertices = [access_by_id[member] for member in members]
        selected.update(cluster_local_heads(member_vertices, feasible_ids, selected, pop_by_id))

    # Pass 2: home every vertex to its nearest two facilities, reusing the placed
    # heads before opening any new build.
    for access in inputs.access_vertices:
        completed = complete_homes(access, [], selected, feasible_ids, pop_by_id)
        homes[access.id] = completed
        selected.update(completed)

    access_edges = [
        AccessEdge(
            access_id, aggregation_id,
            haversine_miles(access_by_id[access_id], pop_by_id[aggregation_id]),
        )
        for access_id, aggregations in homes.items()
        for aggregation_id in aggregations
    ]
    return access_edges, selected

def evaluate_cores(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    plan: _SearchPlan,
) -> tuple[list[AccessEdge], set[str]] | None:
    """Score a core set's feasibility and access homing without routing paths.

    Returns None when the cores do not full-mesh, a forced aggregation cannot
    dual-home, or some access vertex cannot reach two facilities. Routed paths are
    deferred to the winning set, since they do not affect the strength ranking.
    """
    if not cores_mesh(core_ids, inputs.all_distances):
        return None
    if not forced_can_dual_home(core_ids, inputs, plan):
        return None
    return assign_access(core_ids, inputs, plan)

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
    plan: _SearchPlan,
) -> Design | None:
    """Assemble a full three-tier design for one fixed set of core PoPs.

    Returns None if the cores cannot full-mesh, a forced aggregation cannot
    dual-home to them, or some access vertex cannot reach two facilities.
    """
    evaluation = evaluate_cores(core_ids, inputs, plan)
    if evaluation is None:
        return None
    access_edges, selected = evaluation
    path_uses = routed_path_uses(core_ids, inputs, selected)
    draft = _DesignDraft(access_edges, selected, path_uses)
    return finalize_design(core_ids, inputs, draft)

def compute_eligible_ids(
    carrier_pops: list[Vertex],
    roles: dict[str, str],
    adjacency: dict[str, list[tuple[str, float]]],
    allow_roadm_aggregation: bool,
) -> set[str]:
    """Carrier PoPs that may serve as core or aggregation vertices.

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
    carrier_pops: list[Vertex],
    adjacency: dict[str, list[tuple[str, float]]],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, str]]]:
    """Run Dijkstra from every Carrier PoP for reuse across core sets."""
    all_distances: dict[str, dict[str, float]] = {}
    all_predecessors: dict[str, dict[str, str]] = {}
    for pop in carrier_pops:
        all_distances[pop.id], all_predecessors[pop.id] = dijkstra(adjacency, pop.id)
    return all_distances, all_predecessors

def validate_pop_graph(
    carrier_pops: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    adjacency: dict[str, list[tuple[str, float]]],
) -> None:
    """Raise if the physical edge graph and Carrier PoP set are inconsistent."""
    pop_ids = {pop.id for pop in carrier_pops}
    physical_vertex_ids = {vertex_id for edge in physical_edges for vertex_id in edge}
    if not pop_ids.issuperset(physical_vertex_ids):
        raise ValueError("Physical edge graph references unknown Carrier PoP IDs")
    missing_pops = sorted(pop_ids - set(adjacency))
    if missing_pops:
        names = ", ".join(vertex.name for vertex in carrier_pops if vertex.id in missing_pops)
        raise ValueError(f"Carrier PoPs missing from physical edge graph: {names}")

@dataclass(frozen=True)
class _SearchPlan:
    """Pre-computed context shared across every candidate core set.

    ``clusters`` comes from density-clustering the access vertices once (geography
    is core-independent); each cluster's heads are then chosen relative to its
    own extent. ``feasibility_cache`` memoizes per-pair vertex-disjoint
    reachability so the search avoids re-running max-flows for every core set.
    """

    core_candidates: list[str]
    forced_aggregation_ids: frozenset[str]
    strength_by_id: dict[str, float]
    clusters: list[list[str]] = field(default_factory=list)
    feasibility_cache: dict[tuple[str, str, str], bool] = field(default_factory=dict)
    required_cores: frozenset[str] = field(default_factory=frozenset)

def nearest_pop_id(access: Vertex, carrier_pops: list[Vertex]) -> str:
    """Id of the Carrier PoP nearest to an access site."""
    return min(carrier_pops, key=lambda pop: haversine_miles(access, pop)).id

def core_set_strength(core_ids: tuple[str, ...], plan: _SearchPlan) -> float:
    """Total strength of a core set: the primary objective the search maximizes."""
    return sum(plan.strength_by_id[core_id] for core_id in core_ids)

def free_core_candidates(plan: _SearchPlan) -> list[str]:
    """Core candidates the search may choose freely, excluding required cores."""
    return [pop_id for pop_id in plan.core_candidates if pop_id not in plan.required_cores]

def core_combination_count(plan: _SearchPlan, size: int) -> int:
    """How many core sets of ``size`` exist once required cores are fixed in."""
    required = len(plan.required_cores)
    if required > size:
        return 0
    return math.comb(len(free_core_candidates(plan)), size - required)

def core_combinations(plan: _SearchPlan, size: int) -> list[tuple[str, ...]]:
    """Every ``size``-core set, with the required cores fixed into each one."""
    required = tuple(sorted(plan.required_cores))
    if len(required) > size:
        return []
    free = free_core_candidates(plan)
    return [
        required + extra
        for extra in itertools.combinations(free, size - len(required))
    ]

def best_design_at_size(
    inputs: DesignInputs,
    plan: _SearchPlan,
    size: int,
) -> Design | None:
    """Strongest feasible design using exactly ``size`` cores, or None.

    Any operator-forced cores are fixed into every candidate set; the rest are
    chosen by strength (the spec forbids mileage as a design cost),
    with total last-mile only breaking ties among equally strong sets. Core sets
    are tried strongest-first and scored cheaply (feasibility plus access homing,
    no routed paths). Because strength is non-increasing down that order, the
    moment a feasible set is in hand the search stops as soon as a candidate is
    strictly weaker. Routed paths are reconstructed only for the winning set.
    """
    combos = sorted(
        core_combinations(plan, size),
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
        evaluation = evaluate_cores(core_set, inputs, plan)
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
    return build_design_for_cores(best_core_set, inputs, plan)

def total_memory_bytes() -> int:
    """Physical RAM installed on this machine, in bytes (portable across OSes)."""
    return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")

def enumeration_limit(memory_bytes: int, params: DesignParams) -> int:
    """How many core sets fit in the share of RAM the enumeration may use."""
    return int(
        memory_bytes * params.tuning.enum_memory_fraction / params.tuning.core_set_peak_bytes
    )

def search_best_design(
    inputs: DesignInputs,
    params: DesignParams,
    plan: _SearchPlan,
) -> Design:
    """Build the strongest feasible design using exactly ``core_count`` cores.

    The core count is fixed by the operator: the strongest feasible set of that
    size wins, with total last-mile only breaking ties. Enumerating that many
    core sets must fit in the share of RAM the search may use, or the design is
    refused rather than risk exhausting memory.
    """
    limit = enumeration_limit(total_memory_bytes(), params)
    sets = core_combination_count(plan, params.core_count)
    logger.info(
        "Optimizing %d access sites; %d cores, %d required; %d core sets (limit %d)",
        len(inputs.access_vertices), params.core_count, len(plan.required_cores), sets, limit,
    )
    if sets > limit:
        raise ValueError(
            f"Enumerating {sets} core sets of size {params.core_count} "
            f"exceeds the RAM budget of {limit}"
        )
    design = best_design_at_size(inputs, plan, params.core_count)
    if design is None:
        raise ValueError(f"No feasible design with {params.core_count} cores")
    logger.info("Selected a %d-core design", len(design.core_ids))
    return design

@dataclass(frozen=True)
class _GraphContext:
    """Vertex partition and precomputed shortest-path context shared across cores."""

    carrier_pops: list[Vertex]
    all_access: list[Vertex]
    adjacency: dict[str, list[tuple[str, float]]]
    all_distances: dict[str, dict[str, float]]
    all_predecessors: dict[str, dict[str, str]]

def graph_context(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> _GraphContext:
    """Split vertices into PoPs/access and precompute the shared graph context."""
    carrier_pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    all_access = [vertex for vertex in vertices if not is_carrier_pop(vertex)]
    adjacency = unit_adjacency(physical_edges)
    validate_pop_graph(carrier_pops, physical_edges, adjacency)
    all_distances, all_predecessors = all_pairs_shortest(carrier_pops, adjacency)
    return _GraphContext(carrier_pops, all_access, adjacency, all_distances, all_predecessors)

def build_search_plan(
    inputs: DesignInputs,
    eligible_ids: set[str],
    forced: frozenset[str],
    forced_core_ids: frozenset[str],
    params: DesignParams,
) -> _SearchPlan:
    """Compute vertex strengths, access-vertex clusters, and core candidates.

    Required cores are the operator-forced cores; forced aggregations (co-located
    ``AGGR`` vertices and any operator-pinned PoP) are never free core candidates.
    """
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    max_degree = max((len(inputs.adjacency[pop_id]) for pop_id in eligible_ids), default=1)
    strength_by_id = {
        pop_id: core_strength(pop_id, inputs, pop_by_id, max_degree, params.tuning.compass_octants)
        for pop_id in eligible_ids
    }
    clusters, _sparse, _radius = cluster_access_vertices(
        inputs.access_vertices,
        params.tuning.cluster_min_points,
        params.tuning.cluster_min_radius_miles,
        params.tuning.cluster_max_radius_miles,
    )
    core_candidates = sorted(
        eligible_ids - forced, key=lambda pop_id: (-strength_by_id[pop_id], pop_id)
    )
    required = forced_core_ids & eligible_ids
    return _SearchPlan(
        core_candidates, forced, strength_by_id, clusters=clusters,
        required_cores=frozenset(required),
    )

def pop_id_by_name(carrier_pops: list[Vertex]) -> dict[str, str]:
    """Map each Carrier PoP's display name to its vertex id for pin resolution."""
    return {pop.name: pop.id for pop in carrier_pops}

def resolve_pinned_ids(
    names: tuple[str, ...], name_to_id: dict[str, str], label: str
) -> set[str]:
    """Resolve operator-supplied PoP names to ids, rejecting any unknown name."""
    resolved: set[str] = set()
    for name in names:
        if name not in name_to_id:
            raise ValueError(f"--{label} PoP not found in the Carrier graph: {name}")
        resolved.add(name_to_id[name])
    return resolved

def reject_override_conflicts(
    forced_core: set[str], forced_aggregation: set[str], excluded: set[str]
) -> None:
    """Reject an excluded PoP that is also pinned as a core or aggregation."""
    clash = excluded & (forced_core | forced_aggregation)
    if clash:
        raise ValueError(f"PoPs cannot be both excluded and forced: {sorted(clash)}")

def colocated_twin(core: Vertex) -> Vertex:
    """Build the co-located ``AGGR`` vertex that shares a core's coordinates."""
    return Vertex(
        id=f"aggr_{core.id}",
        name=f"AGGR {core.name}",
        tenant=core.tenant,
        kind=core.kind,
        coords=core.coords,
        description=core.description,
        shown_in_map=core.shown_in_map,
    )

def colocation_edges(
    core_id: str, twin_id: str, physical_edges: dict[tuple[str, str], PhysicalEdge]
) -> dict[tuple[str, str], PhysicalEdge]:
    """Edges standing up a co-located ``AGGR`` stack beside its core.

    A zero-mile in-facility cross-connect joins the two distinct hardware stacks,
    and every one of the core's fiber handoffs is duplicated onto the aggregation
    so it reaches a remote core without traversing its own co-located core.
    """
    facility = edge_key(core_id, twin_id)
    new_edges: dict[tuple[str, str], PhysicalEdge] = {
        facility: PhysicalEdge(
            source=facility[0], target=facility[1], distance_miles=0.0,
            note="in-facility core/aggregation cross-connect",
        )
    }
    for (left, right), edge in physical_edges.items():
        neighbor = right if left == core_id else left if right == core_id else None
        if neighbor is None:
            continue
        handoff = edge_key(twin_id, neighbor)
        new_edges[handoff] = PhysicalEdge(
            source=handoff[0], target=handoff[1], distance_miles=edge.distance_miles,
            source_page=edge.source_page, note="co-located aggregation fiber handoff",
        )
    return new_edges

def split_colocated(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    colocated_ids: set[str],
) -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge], dict[str, str]]:
    """Split each co-located PoP into its core vertex and a co-located ``AGGR`` twin."""
    vertex_by_id = {vertex.id: vertex for vertex in vertices}
    augmented_vertices = list(vertices)
    augmented_edges = dict(physical_edges)
    twin_by_core: dict[str, str] = {}
    for core_id in sorted(colocated_ids):
        twin = colocated_twin(vertex_by_id[core_id])
        twin_by_core[core_id] = twin.id
        augmented_vertices.append(twin)
        augmented_edges.update(colocation_edges(core_id, twin.id, physical_edges))
    return augmented_vertices, augmented_edges, twin_by_core

def apply_role_overrides(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    params: DesignParams,
) -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge], RoleOverrides]:
    """Resolve operator role pins and split any co-located PoP into two vertices.

    Returns the (possibly augmented) vertices and physical edges plus the resolved
    ``RoleOverrides``. A PoP pinned as both a core and an aggregation becomes a
    ``CORE`` vertex (kept under its own id) and a co-located ``AGGR`` twin, and it is
    the twin's id that enters ``forced_aggregation_ids``.
    """
    carrier_pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    name_to_id = pop_id_by_name(carrier_pops)
    forced_core = resolve_pinned_ids(params.forced_core_names, name_to_id, "force-core")
    forced_aggregation = resolve_pinned_ids(
        params.forced_aggregation_names, name_to_id, "force-aggregation"
    )
    excluded = resolve_pinned_ids(params.excluded_names, name_to_id, "exclude")
    reject_override_conflicts(forced_core, forced_aggregation, excluded)
    colocated = forced_core & forced_aggregation
    vertices, physical_edges, twin_by_core = split_colocated(vertices, physical_edges, colocated)
    forced_aggregation_ids = (forced_aggregation - colocated) | set(twin_by_core.values())
    overrides = RoleOverrides(
        forced_core_ids=frozenset(forced_core),
        forced_aggregation_ids=frozenset(forced_aggregation_ids),
        excluded_ids=frozenset(excluded),
    )
    return vertices, physical_edges, overrides

def optimize_three_tier_design(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    roles: dict[str, str],
    params: DesignParams,
    overrides: RoleOverrides | None = None,
) -> Design:
    """Optimize a three-tier WAN over the Carrier graph for the given parameters.

    ``overrides`` carries operator role pins already resolved to vertex ids (with any
    co-located PoP split in ``vertices``/``physical_edges``); pass ``None`` for an
    unpinned design.
    """
    overrides = overrides if overrides is not None else RoleOverrides()
    if params.core_count < 2:
        raise ValueError("core_count (the number of cores) must be at least 2")

    context = graph_context(vertices, physical_edges)
    forced = overrides.forced_aggregation_ids
    eligible_ids = compute_eligible_ids(
        context.carrier_pops, roles, context.adjacency, params.allow_roadm_aggregation
    )
    eligible_ids = (eligible_ids | forced | overrides.forced_core_ids) - overrides.excluded_ids
    if len(eligible_ids) < max(2, params.core_count):
        raise ValueError("Not enough eligible Carrier aggregation/core PoPs")

    inputs = DesignInputs(
        access_vertices=context.all_access,
        carrier_pops=context.carrier_pops,
        physical_edges=physical_edges,
        eligible_aggregation_ids=eligible_ids,
        adjacency=context.adjacency,
        all_distances=context.all_distances,
        all_predecessors=context.all_predecessors,
    )
    plan = build_search_plan(
        inputs, eligible_ids, forced, overrides.forced_core_ids, params
    )
    if len(plan.core_candidates) < params.core_count:
        raise ValueError("Not enough reachable core candidates")
    return search_best_design(inputs, params, plan)
