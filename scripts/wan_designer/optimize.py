"""Optimize a three-tier core/aggregation/access WAN over the carrier graph.

Cores are chosen for strength, not mileage (the source mapbook has no
distances): each core's strength is its degree plus compass spread plus path
straightness, and for a given core count the strongest feasible set wins, with
total last-mile only breaking ties. Salt Lake City is required as a core to
anchor the mountain-west, where the three Sentinel wings concentrate their
demand. The number of cores is not fixed at the minimum: the search sweeps core
counts upward and keeps adding a core while doing so meaningfully shortens how
far demand sits from its cores (in hops, weighted by the sites behind each
aggregation), stopping once extra cores stop helping.

The three Sentinel bases are forced into the aggregation tier at their
co-located PoPs; access sites with no aggregation within the last-mile cap are
exempt from the cap and home to their nearest two regardless.

On top of the algorithm, the operator may pin roles by PoP name (``RoleOverrides``,
resolved by ``apply_role_overrides``): force a PoP to be a core, force it to be an
aggregation, or exclude it from every selected role. A PoP forced as both a core
and an aggregation is co-located: it is split into a distinct ``CORE`` node and a
co-located ``AGGR`` node that share coordinates and a zero-mile in-facility
cross-connect, with the core's fiber duplicated onto the aggregation's distinct
hardware stack so the aggregation reaches its own co-located core as one of its two
node-disjoint cores and a remote core as the other (see ``apply_role_overrides``).
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
    Node,
    PathUse,
    PhysicalEdge,
    RoleOverrides,
    edge_key,
    haversine_miles,
)
from wan_designer.graphs import (
    dijkstra,
    node_disjoint_paths_to_cores,
    path_edge_keys,
    reconstruct_path,
)
from wan_designer.clustering import cluster_access_nodes

COMPASS_OCTANTS = 8

# The Sentinel ICBM wings, forced into the aggregation tier at their PoPs.
SENTINEL_BASE_NAMES = ("Malmstrom AFB", "Minot AFB", "F.E. Warren AFB")

# PoPs required as cores regardless of raw strength, to anchor a region whose
# demand justifies a core. Salt Lake City anchors the mountain-west, where the
# three Sentinel wings concentrate 165 sites each behind Minot, Great Falls,
# and Cheyenne.
REQUIRED_CORE_NAMES = ("Salt Lake City, UT",)

# Modeled demand behind each Sentinel base, used to weight how heavily a base's
# distance to its cores counts when deciding how many cores the design needs.
SENTINEL_SITE_COUNT = 165

# Peak bytes one enumerated-and-sorted core set costs (the tuple, its list slot,
# and the transient the sort holds). Used to size the search to the machine's
# actual memory instead of a hand-picked cap.
CORE_SET_PEAK_BYTES = 160

# Share of the machine's RAM the core enumeration may use at its peak. The rest
# is headroom for the operating system and the rest of the program.
ENUM_MEMORY_FRACTION = 0.6

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

def cluster_diameter(members: list[Node]) -> float:
    """The farthest great-circle distance between any two members of a cluster."""
    return max(
        (haversine_miles(left, right) for left in members for right in members),
        default=0.0,
    )

def cluster_local_heads(
    members: list[Node],
    feasible_ids: set[str],
    pop_by_id: dict[str, Node],
) -> list[str]:
    """Up to two distinct feasible PoPs local to a cluster, its heads.

    A PoP is local when it sits within the cluster's own extent -- its diameter,
    the farthest distance between two members -- of at least one member, so a
    head is never much farther from the cluster than the cluster is wide. The two
    locals nearest the cluster as a whole (least total distance to its members)
    become its intentional aggregation heads. A distant PoP (Boise, ~243 mi from
    the nearest Utah member, well beyond that cluster's ~100 mi extent) is never
    built as the cluster's head; that cluster's second home comes from reuse.
    """
    diameter = cluster_diameter(members)
    scored: list[tuple[float, str]] = []
    for aggregation_id in feasible_ids:
        pop = pop_by_id[aggregation_id]
        if min(haversine_miles(member, pop) for member in members) <= diameter:
            total = sum(haversine_miles(member, pop) for member in members)
            scored.append((total, aggregation_id))
    scored.sort()
    return [aggregation_id for _total, aggregation_id in scored[:2]]

def complete_homes(
    access: Node,
    current: list[str],
    selected: set[str],
    feasible_ids: set[str],
    pop_by_id: dict[str, Node],
) -> list[str]:
    """Fill an access node out toward two homes, preferring reuse over a build.

    Existing facilities (cluster heads already placed, forced bases) are reused
    first; a new aggregation is opened only when fewer than two existing
    facilities are reachable -- the last resort for a lone node or a synthetic
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
    plan: _SearchPlan,
) -> tuple[list[AccessEdge], set[str]] | None:
    """Home every access node by clustering: cluster heads first, then reuse.

    Aggregations are placed as the heads of dense access-node clusters (two
    distinct local PoPs each). Every node then dual-homes to two facilities,
    completing any gap (a cluster with one local head, or a sparse lone node) by
    reusing an existing facility rather than building a redundant one. Returns
    the access edges and selected aggregation ids, or None if some node cannot
    reach two facilities.
    """
    feasible_ids = feasible_aggregation_ids(core_ids, inputs, plan)
    if len(feasible_ids) < 2:
        return None
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    access_by_id = {access.id: access for access in inputs.access_nodes}
    selected: set[str] = set(plan.forced_aggregation_ids)
    homes: dict[str, list[str]] = {}

    # Pass 1: stand up each cluster's local aggregation heads.
    for members in plan.clusters:
        member_nodes = [access_by_id[member] for member in members]
        heads = cluster_local_heads(member_nodes, feasible_ids, pop_by_id)
        if not heads:
            continue
        selected.update(heads)
        for member in members:
            homes[member] = list(heads)

    # Pass 2: complete every node to two homes, reusing existing facilities.
    for access in inputs.access_nodes:
        if len(homes.get(access.id, [])) >= 2:
            continue
        completed = complete_homes(
            access, homes.get(access.id, []), selected, feasible_ids, pop_by_id
        )
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
    dual-home, or some access node cannot reach two facilities. Routed paths are
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
    dual-home to them, or some access node cannot reach two facilities.
    """
    evaluation = evaluate_cores(core_ids, inputs, plan)
    if evaluation is None:
        return None
    access_edges, selected = evaluation
    path_uses = routed_path_uses(core_ids, inputs, selected)
    draft = _DesignDraft(access_edges, selected, path_uses)
    return finalize_design(core_ids, inputs, draft)

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

    ``clusters`` comes from density-clustering the access nodes once (geography
    is core-independent); each cluster's heads are then chosen relative to its
    own extent. ``feasibility_cache`` memoizes per-pair node-disjoint
    reachability so the search avoids re-running max-flows for every core set.
    """

    core_candidates: list[str]
    forced_aggregation_ids: frozenset[str]
    strength_by_id: dict[str, float]
    clusters: list[list[str]] = field(default_factory=list)
    feasibility_cache: dict[tuple[str, str, str], bool] = field(default_factory=dict)
    required_cores: frozenset[str] = field(default_factory=frozenset)
    sentinel_ids: frozenset[str] = field(default_factory=frozenset)

def nearest_pop_id(access: Node, carrier_pops: list[Node]) -> str:
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

    The required cores (e.g. Salt Lake City) are fixed into every candidate set;
    the rest are chosen by strength (the spec forbids mileage as a design cost),
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

def aggregation_demand(design: Design, plan: _SearchPlan) -> dict[str, int]:
    """Sites behind each aggregation: its homed access count, or 165 for a base.

    Only the Sentinel bases carry the modeled 165-site demand; an operator-forced
    aggregation (Herndon, a co-located ``AGGR``) is weighted by the access sites it
    actually homes, like any ordinary aggregation.
    """
    demand: dict[str, int] = {}
    for edge in design.access_edges:
        demand[edge.target] = demand.get(edge.target, 0) + 1
    for aggregation_id in plan.sentinel_ids:
        demand[aggregation_id] = SENTINEL_SITE_COUNT
    return demand

def coverage_score(design: Design, plan: _SearchPlan) -> float:
    """Total traffic-distance to the cores: lower means demand sits nearer a core.

    Each aggregation's two routed paths to its cores are counted in hops and
    weighted by the sites behind it, so a base's 165 sites pull far harder than a
    single access link. Hops avoid mileage, which the spec forbids as a cost.
    """
    demand = aggregation_demand(design, plan)
    total = 0.0
    for use in design.path_uses:
        if use.purpose == "aggregation_to_core":
            total += demand.get(use.source, 1) * (len(use.path) - 1)
    return total

def total_memory_bytes() -> int:
    """Physical RAM installed on this machine, in bytes (portable across OSes)."""
    return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")

def enumeration_limit(memory_bytes: int) -> int:
    """How many core sets fit in the share of RAM the enumeration may use."""
    return int(memory_bytes * ENUM_MEMORY_FRACTION / CORE_SET_PEAK_BYTES)

def search_best_design(
    inputs: DesignInputs,
    params: DesignParams,
    plan: _SearchPlan,
) -> Design:
    """Find the best design across core counts, not just the fewest that work.

    For each core count from ``core_count`` upward the strongest feasible design
    is built and scored by how near demand sits to its cores. A larger count is
    adopted only when it cuts that traffic-distance by at least
    ``core_coverage_improvement``; once a couple of larger counts fail to clear
    that bar (or enumerating that many core sets would not fit in the machine's
    free RAM) the sweep stops. Every count tried is logged for review.
    """
    limit = enumeration_limit(total_memory_bytes())
    logger.info(
        "Optimizing %d access sites; cores >= %d, %d required; up to %d core sets per size",
        len(inputs.access_nodes), params.core_count, len(plan.required_cores), limit,
    )
    best: Design | None = None
    best_coverage = math.inf
    stale = 0
    for size in range(params.core_count, len(plan.core_candidates) + 1):
        sets = core_combination_count(plan, size)
        if sets > limit:
            logger.info(
                "  %d cores: %d core sets (~%.1f GB) exceed the RAM budget; stopping",
                size, sets, sets * CORE_SET_PEAK_BYTES / 1e9,
            )
            break
        design = best_design_at_size(inputs, plan, size)
        if design is None:
            continue
        coverage = coverage_score(design, plan)
        improvement = (best_coverage - coverage) / best_coverage if best else 1.0
        logger.info(
            "  %d cores -> traffic-to-core %.0f hop-sites (%.1f%% better): %s",
            size, coverage, 100.0 * improvement,
            ", ".join(design.core_ids),
        )
        if best is None or improvement >= params.core_coverage_improvement:
            best, best_coverage, stale = design, coverage, 0
            continue
        stale += 1
        if stale >= 2:
            logger.info("  adding cores past this no longer helps; stopping the sweep")
            break
    if best is None:
        raise ValueError(f"No feasible design with {params.core_count} or more cores")
    logger.info("Selected a %d-core design", len(best.core_ids))
    return best

@dataclass(frozen=True)
class _GraphContext:
    """Node partition and precomputed shortest-path context shared across cores."""

    carrier_pops: list[Node]
    all_access: list[Node]
    adjacency: dict[str, list[tuple[str, float]]]
    all_distances: dict[str, dict[str, float]]
    all_predecessors: dict[str, dict[str, str]]

def graph_context(
    nodes: list[Node],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> _GraphContext:
    """Split nodes into PoPs/access and precompute the shared graph context."""
    carrier_pops = [node for node in nodes if node.kind == "carrier_pop"]
    all_access = [node for node in nodes if node.kind != "carrier_pop"]
    adjacency = unit_adjacency(physical_edges)
    validate_pop_graph(carrier_pops, physical_edges, adjacency)
    all_distances, all_predecessors = all_pairs_shortest(carrier_pops, adjacency)
    return _GraphContext(carrier_pops, all_access, adjacency, all_distances, all_predecessors)

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

def required_core_ids(carrier_pops: list[Node], eligible_ids: set[str]) -> frozenset[str]:
    """Ids of the PoPs that must be cores (e.g. Salt Lake City), when eligible."""
    return frozenset(
        pop.id
        for pop in carrier_pops
        if pop.name in REQUIRED_CORE_NAMES and pop.id in eligible_ids
    )

def build_search_plan(
    inputs: DesignInputs,
    eligible_ids: set[str],
    forced: frozenset[str],
    sentinel_ids: frozenset[str],
    forced_core_ids: frozenset[str],
) -> _SearchPlan:
    """Compute node strengths, access-node clusters, and core candidates.

    Required cores combine the named anchor (Salt Lake City) with any
    operator-forced cores; forced aggregations (Sentinel bases, co-located
    ``AGGR`` nodes, Herndon) are never free core candidates.
    """
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    max_degree = max((len(inputs.adjacency[pop_id]) for pop_id in eligible_ids), default=1)
    strength_by_id = {
        pop_id: core_strength(pop_id, inputs, pop_by_id, max_degree)
        for pop_id in eligible_ids
    }
    clusters, _sparse, _radius = cluster_access_nodes(inputs.access_nodes)
    core_candidates = sorted(
        eligible_ids - forced, key=lambda pop_id: (-strength_by_id[pop_id], pop_id)
    )
    required = required_core_ids(inputs.carrier_pops, eligible_ids) | (
        forced_core_ids & eligible_ids
    )
    return _SearchPlan(
        core_candidates, forced, strength_by_id, clusters=clusters,
        required_cores=frozenset(required), sentinel_ids=sentinel_ids,
    )

def pop_id_by_name(carrier_pops: list[Node]) -> dict[str, str]:
    """Map each Carrier PoP's display name to its node id for pin resolution."""
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

def colocated_twin(core: Node) -> Node:
    """Build the co-located ``AGGR`` node that shares a core's coordinates."""
    return Node(
        id=f"aggr_{core.id}",
        name=f"AGGR {core.name}",
        category=core.category,
        kind=core.kind,
        lat=core.lat,
        lon=core.lon,
        description=core.description,
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
    nodes: list[Node],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    colocated_ids: set[str],
) -> tuple[list[Node], dict[tuple[str, str], PhysicalEdge], dict[str, str]]:
    """Split each co-located PoP into its core node and a co-located ``AGGR`` twin."""
    node_by_id = {node.id: node for node in nodes}
    augmented_nodes = list(nodes)
    augmented_edges = dict(physical_edges)
    twin_by_core: dict[str, str] = {}
    for core_id in sorted(colocated_ids):
        twin = colocated_twin(node_by_id[core_id])
        twin_by_core[core_id] = twin.id
        augmented_nodes.append(twin)
        augmented_edges.update(colocation_edges(core_id, twin.id, physical_edges))
    return augmented_nodes, augmented_edges, twin_by_core

def apply_role_overrides(
    nodes: list[Node],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    params: DesignParams,
) -> tuple[list[Node], dict[tuple[str, str], PhysicalEdge], RoleOverrides]:
    """Resolve operator role pins and split any co-located PoP into two nodes.

    Returns the (possibly augmented) nodes and physical edges plus the resolved
    ``RoleOverrides``. A PoP pinned as both a core and an aggregation becomes a
    ``CORE`` node (kept under its own id) and a co-located ``AGGR`` twin, and it is
    the twin's id that enters ``forced_aggregation_ids``.
    """
    carrier_pops = [node for node in nodes if node.kind == "carrier_pop"]
    name_to_id = pop_id_by_name(carrier_pops)
    forced_core = resolve_pinned_ids(params.forced_core_names, name_to_id, "force-core")
    forced_aggregation = resolve_pinned_ids(
        params.forced_aggregation_names, name_to_id, "force-aggregation"
    )
    excluded = resolve_pinned_ids(params.excluded_names, name_to_id, "exclude")
    reject_override_conflicts(forced_core, forced_aggregation, excluded)
    colocated = forced_core & forced_aggregation
    nodes, physical_edges, twin_by_core = split_colocated(nodes, physical_edges, colocated)
    forced_aggregation_ids = (forced_aggregation - colocated) | set(twin_by_core.values())
    overrides = RoleOverrides(
        forced_core_ids=frozenset(forced_core),
        forced_aggregation_ids=frozenset(forced_aggregation_ids),
        excluded_ids=frozenset(excluded),
    )
    return nodes, physical_edges, overrides

def optimize_three_tier_design(
    nodes: list[Node],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    roles: dict[str, str],
    params: DesignParams,
    overrides: RoleOverrides | None = None,
) -> Design:
    """Optimize a three-tier WAN over the Carrier graph for the given parameters.

    ``overrides`` carries operator role pins already resolved to node ids (with any
    co-located PoP split in ``nodes``/``physical_edges``); pass ``None`` for an
    unpinned design.
    """
    overrides = overrides if overrides is not None else RoleOverrides()
    if params.core_count < 2:
        raise ValueError("core_count (the minimum number of cores) must be at least 2")

    context = graph_context(nodes, physical_edges)
    sentinel_ids, access_nodes = sentinel_split(context.all_access, context.carrier_pops)
    forced = sentinel_ids | overrides.forced_aggregation_ids
    eligible_ids = compute_eligible_ids(
        context.carrier_pops, roles, context.adjacency, params.allow_roadm_aggregation
    )
    eligible_ids = (eligible_ids | forced | overrides.forced_core_ids) - overrides.excluded_ids
    if len(eligible_ids) < max(2, params.core_count):
        raise ValueError("Not enough eligible Carrier aggregation/core PoPs")

    inputs = DesignInputs(
        access_nodes=access_nodes,
        carrier_pops=context.carrier_pops,
        physical_edges=physical_edges,
        eligible_aggregation_ids=eligible_ids,
        adjacency=context.adjacency,
        all_distances=context.all_distances,
        all_predecessors=context.all_predecessors,
    )
    plan = build_search_plan(
        inputs, eligible_ids, forced, sentinel_ids, overrides.forced_core_ids
    )
    if len(plan.core_candidates) < params.core_count:
        raise ValueError("Not enough reachable core candidates")
    return search_best_design(inputs, params, plan)
