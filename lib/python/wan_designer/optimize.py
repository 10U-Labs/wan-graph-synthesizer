"""Optimize a three-tier core/aggregation/access WAN over the carrier graph.

Cores are chosen for strength, not mileage (the source mapbook has no
distances): each core's strength is its degree plus compass spread plus path
straightness, and the strongest feasible set of at least the configured
``min_core_count`` wins, with total last-mile only breaking ties. The tier then
grows past that floor while any aggregation is farther than
``core_coverage_target_miles`` from every core, each added core being the one that
most shortens the aggregation-to-core haul -- so extra cores appear only where they
bring demand closer, never as a mileage cost minimized over candidate sets.

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
from dataclasses import dataclass, field, replace

from wan_designer.model import (
    AccessEdge,
    Design,
    DesignInputs,
    DesignMetrics,
    DesignParams,
    ForcedLinks,
    Vertex,
    PathUse,
    PhysicalEdge,
    RoleOverrides,
    edge_key,
    haversine_miles,
    is_carrier_pop,
)
from wan_designer.forced import (
    apply_forced_access_homes,
    forced_cores_for_aggregation,
    required_core_pairs,
)
from wan_designer.graphs import (
    dijkstra,
    vertex_disjoint_paths_to_cores,
    path_edge_keys,
)
from wan_designer.backbone import BackboneConstraints, core_mesh_paths, path_geometry_miles
from wan_designer.clustering import cluster_access_vertices
from wan_designer.overrides import colocated_twin, colocation_edges, twin_vertex_id
from wan_designer.strength import core_strength

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

def aggregation_core_paths(
    aggregation_id: str,
    core_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    required_cores: frozenset[str] = frozenset(),
) -> tuple[float, list[PathUse]]:
    """Route an aggregation to two distinct cores over vertex-disjoint paths.

    ``required_cores`` are operator-forced cores this aggregation must home to;
    each is forced to anchor one of the two routed paths.
    """
    total, paths = vertex_disjoint_paths_to_cores(
        adjacency, aggregation_id, core_ids, 2, required_cores
    )
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

def cores_reachable_avoiding(
    pop_id: str,
    adjacency: dict[str, list[tuple[str, float]]],
) -> set[str]:
    """PoPs reachable from ``pop_id``'s neighbors without passing through ``pop_id``.

    A co-located twin reaches its own (selected) core for free over the in-facility
    cross-connect, so its second vertex-disjoint path only has to reach a *different*
    core while bypassing the core they share. That second path exists exactly when
    one of the core's neighbors can reach another core with the core itself removed,
    which this breadth-first reachability answers once per candidate.
    """
    frontier = [
        neighbor for neighbor, _weight in adjacency.get(pop_id, []) if neighbor != pop_id
    ]
    reached = set(frontier)
    while frontier:
        node = frontier.pop()
        for neighbor, _weight in adjacency.get(node, []):
            if neighbor != pop_id and neighbor not in reached:
                reached.add(neighbor)
                frontier.append(neighbor)
    return reached

def feasible_colocation_twins(core_ids: tuple[str, ...], plan: _SearchPlan) -> set[str]:
    """Twin ids whose own core is selected and that keep two-distinct-core redundancy.

    A core's twin is offered as an aggregation only when its core is in the set and
    another core is reachable around it, so the twin keeps two vertex-disjoint paths
    to two distinct cores -- itself over the cross-connect and the remote core beyond.
    """
    core_set = set(core_ids)
    twins = plan.aggregations
    return {
        twin_id
        for twin_id, core_id in twins.twin_to_core.items()
        if core_id in core_set and twins.reach_avoiding[core_id] & core_set
    }

def feasible_aggregation_ids(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    plan: _SearchPlan,
) -> set[str]:
    """Eligible aggregations that can dual-home to two of the given cores.

    Includes the co-located twin of any selected core that can still dual-home (see
    :func:`feasible_colocation_twins`), so the search may let a core also serve as an
    aggregation. Only feasibility is computed here -- routed paths are reconstructed
    once for the winning core set -- because the design is ranked solely on last-mile
    mileage and core strength, neither of which depends on those paths.
    """
    pairs = core_pairs(core_ids)
    candidates = inputs.eligible_aggregation_ids - set(core_ids)
    feasible = {
        aggregation_id
        for aggregation_id in candidates
        if aggregation_dual_homes(aggregation_id, pairs, inputs, plan.feasibility_cache)
    }
    return feasible | feasible_colocation_twins(core_ids, plan)

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
    draft: _DesignDraft,
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> Design:
    """Compute edge sets, mileage estimate, and score for a design draft.

    ``physical_edges`` carries the base graph plus the fiber of every seated
    co-located twin, so a dual-roled core's aggregation path resolves its mileage.
    """
    physical_edge_keys: set[tuple[str, str]] = set()
    for path_use in draft.path_uses:
        physical_edge_keys.update(path_edge_keys(path_use.path))

    access_miles = sum(edge.distance_miles for edge in draft.access_edges)
    physical_miles = sum(
        physical_edges[key].distance_miles for key in physical_edge_keys
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

def effective_forced_aggregations(plan: _SearchPlan) -> set[str]:
    """The aggregations every design must seat: the operator's pins.

    Installation facilities are preferred heads rather than hard requirements (see
    :func:`assign_access`), so they are not gated here -- a justified installation
    that cannot dual-home to a given core set simply is not seated for that set.
    """
    return set(plan.aggregations.operator_forced)


def forced_can_dual_home(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    plan: _SearchPlan,
) -> bool:
    """True if every forced aggregation can dual-home to two of the cores."""
    pairs = core_pairs(core_ids)
    return all(
        aggregation_dual_homes(forced_id, pairs, inputs, plan.feasibility_cache)
        for forced_id in effective_forced_aggregations(plan)
    )

def prune_unused_aggregations(
    selected: set[str], access_edges: list[AccessEdge], pinned: frozenset[str]
) -> set[str]:
    """Drop seated aggregations no access vertex homes to, keeping operator pins.

    A population anchor (a state's metro slot) can be seated where demand never
    reaches -- e.g. a second-metro city that outranks a smaller metro on paper while
    every access node clusters near the smaller one -- leaving an aggregation that
    aggregates nothing. Such facilities are dropped so the tier stays demand-driven.
    Operator-forced pins are intentional regardless of demand and are always kept.
    """
    homed = {edge.target for edge in access_edges}
    return {
        aggregation_id
        for aggregation_id in selected
        if aggregation_id in homed or aggregation_id in pinned
    }


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
    pop_by_id.update(plan.aggregations.twin_vertices)
    access_by_id = {access.id: access for access in inputs.access_vertices}
    selected: set[str] = set(effective_forced_aggregations(plan))
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
    # heads before opening any new build. An operator-forced access link pins one
    # of that vertex's two homes regardless of distance.
    for access in inputs.access_vertices:
        completed = complete_homes(access, [], selected, feasible_ids, pop_by_id)
        completed = apply_forced_access_homes(access, completed, plan.forced_links, pop_by_id)
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
    selected = prune_unused_aggregations(selected, access_edges, plan.aggregations.operator_forced)
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

def physical_edges_with_twins(
    selected: set[str],
    inputs: DesignInputs,
    plan: _SearchPlan,
) -> dict[tuple[str, str], PhysicalEdge]:
    """The base physical edges plus the fiber of every selected co-located twin."""
    edges = dict(inputs.physical_edges)
    for aggregation_id in selected:
        core_id = plan.aggregations.twin_to_core.get(aggregation_id)
        if core_id is not None:
            edges.update(colocation_edges(core_id, aggregation_id, inputs.physical_edges))
    return edges

def twin_routing_adjacency(
    aggregation_id: str,
    inputs: DesignInputs,
    plan: _SearchPlan,
) -> dict[str, list[tuple[str, float]]]:
    """Adjacency to route one aggregation: the base graph, plus its own twin fiber.

    A real aggregation routes over the base graph unchanged. A co-located twin gets
    only *its own* cross-connect and duplicated handoffs added, so it reaches its core
    and a remote core without another core's twin fiber leaking into the path.
    """
    core_id = plan.aggregations.twin_to_core.get(aggregation_id)
    if core_id is None:
        return inputs.adjacency
    twin_edges = colocation_edges(core_id, aggregation_id, inputs.physical_edges)
    return unit_adjacency({**inputs.physical_edges, **twin_edges})

def routed_path_uses(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    selected: set[str],
    plan: _SearchPlan,
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> list[PathUse]:
    """Reconstruct the core-mesh and aggregation-to-core paths for a design."""
    core_set = set(core_ids)
    constraints = BackboneConstraints(
        plan.core_backbone_min_degree, required_core_pairs(core_set, plan.forced_links)
    )
    path_uses = core_mesh_paths(
        core_ids, inputs.all_distances, inputs.all_predecessors, physical_edges, constraints
    )
    for aggregation_id in sorted(selected):
        adjacency = twin_routing_adjacency(aggregation_id, inputs, plan)
        _cost, uses = aggregation_core_paths(
            aggregation_id, core_ids, adjacency, physical_edges,
            forced_cores_for_aggregation(aggregation_id, core_set, plan.forced_links),
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
    physical_edges = physical_edges_with_twins(selected, inputs, plan)
    path_uses = routed_path_uses(core_ids, inputs, selected, plan, physical_edges)
    draft = _DesignDraft(access_edges, selected, path_uses)
    return finalize_design(core_ids, draft, physical_edges)

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
class _AggregationPlan:
    """The aggregations a design may seat.

    ``operator_forced`` are the operator's pinned aggregations, always seated. A
    forced installation's co-located twin is one of these, so installations enter
    the aggregation tier only by operator force and never as cores. The remaining
    fields carry the optional co-located twins the search may seat so a core also
    serves as an aggregation: each twin id to its core, each core's reach-around set,
    and the twin vertices whose coordinates (their core's) drive access homing.
    """

    operator_forced: frozenset[str] = frozenset()
    twin_to_core: dict[str, str] = field(default_factory=dict)
    reach_avoiding: dict[str, set[str]] = field(default_factory=dict)
    twin_vertices: dict[str, Vertex] = field(default_factory=dict)


def with_colocation_twins(
    aggregations: _AggregationPlan,
    core_candidates: list[str],
    pop_by_id: dict[str, Vertex],
    adjacency: dict[str, list[tuple[str, float]]],
) -> _AggregationPlan:
    """Offer each core candidate a co-located twin the search may seat as an aggregation.

    Skips any core whose twin already exists -- an operator co-location or a forced
    installation already stands up and pins that twin -- so it is never double-built.
    """
    twin_to_core: dict[str, str] = {}
    reach_avoiding: dict[str, set[str]] = {}
    twin_vertices: dict[str, Vertex] = {}
    for core_id in core_candidates:
        twin_id = twin_vertex_id(core_id)
        if twin_id in pop_by_id:
            continue
        twin_to_core[twin_id] = core_id
        reach_avoiding[core_id] = cores_reachable_avoiding(core_id, adjacency)
        twin_vertices[twin_id] = colocated_twin(pop_by_id[core_id])
    return replace(
        aggregations,
        twin_to_core=twin_to_core,
        reach_avoiding=reach_avoiding,
        twin_vertices=twin_vertices,
    )


@dataclass(frozen=True)
class _SearchPlan:
    """Pre-computed context shared across every candidate core set.

    ``clusters`` comes from density-clustering the access vertices once (geography
    is core-independent); each cluster's heads are then chosen relative to its
    own extent. ``feasibility_cache`` memoizes per-pair vertex-disjoint
    reachability so the search avoids re-running max-flows for every core set.
    ``aggregations`` carries the operator pins and the optional core twins.
    """

    core_candidates: list[str]
    aggregations: _AggregationPlan
    strength_by_id: dict[str, float]
    clusters: list[list[str]] = field(default_factory=list)
    feasibility_cache: dict[tuple[str, str, str], bool] = field(default_factory=dict)
    core_backbone_min_degree: int = 3
    forced_links: ForcedLinks = field(default_factory=ForcedLinks)

    @property
    def required_cores(self) -> frozenset[str]:
        """The operator-forced cores fixed into every candidate set."""
        return self.forced_links.required_cores

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

COVERAGE_EPSILON_MILES = 1.0  # a new core must cut total aggregation haul by at least this


def aggregation_haul_miles(
    core_ids: tuple[str, ...],
    aggregation_ids: tuple[str, ...] | set[str],
    pop_by_id: dict[str, Vertex],
) -> tuple[float, float]:
    """The worst and total straight-line miles from aggregations to their nearest core.

    The coverage signal the search drives down by adding cores: ``worst`` is the
    long-haul an operator sees on the map; ``total`` lets one added core show progress
    even while another still-distant aggregation dominates the worst.
    """
    cores = [pop_by_id[core_id] for core_id in core_ids]
    distances = [
        min(haversine_miles(pop_by_id[aggregation_id], core) for core in cores)
        for aggregation_id in aggregation_ids
    ]
    return max(distances, default=0.0), sum(distances)


def coverage_candidate_totals(
    core_ids: tuple[str, ...],
    free: list[str],
    inputs: DesignInputs,
    plan: _SearchPlan,
    pop_by_id: dict[str, Vertex],
) -> list[tuple[float, str]]:
    """Each free candidate's total aggregation-to-core haul once it joins the cores.

    Infeasible additions (a candidate whose promotion strands demand) are dropped, so
    every returned pair is a buildable grown set ranked by how short it leaves the haul.
    """
    totals: list[tuple[float, str]] = []
    for candidate_id in free:
        candidate_cores = tuple(sorted((*core_ids, candidate_id)))
        evaluation = evaluate_cores(candidate_cores, inputs, plan)
        if evaluation is None:
            continue
        _worst, total = aggregation_haul_miles(candidate_cores, evaluation[1], pop_by_id)
        totals.append((total, candidate_id))
    return totals


def grow_cores_for_coverage(
    base: Design,
    inputs: DesignInputs,
    plan: _SearchPlan,
    params: DesignParams,
    pop_by_id: dict[str, Vertex],
) -> Design:
    """Add cores beyond the strength-chosen base until demand is close enough.

    While some aggregation is farther than ``core_coverage_target_miles`` from every
    core, add the one remaining candidate that most reduces the total aggregation-to-core
    haul, rebuilding the design around it. Extra cores are thus coverage-driven: strength
    still chooses the base tier, and the operator's coverage target is a constraint on
    how far the tier may leave demand, not a mileage cost minimized over candidate
    sets. Growth stops once every aggregation is within target, the tier reaches
    ``max_core_count``, no remaining candidate brings demand meaningfully closer, or
    the candidates are exhausted.
    """
    target_miles = params.tuning.core_coverage_target_miles
    core_ids = base.core_ids
    design = base
    free = [pop_id for pop_id in plan.core_candidates if pop_id not in core_ids]
    while free:
        if params.max_core_count is not None and len(core_ids) >= params.max_core_count:
            break
        worst, total = aggregation_haul_miles(core_ids, design.aggregation_ids, pop_by_id)
        if worst <= target_miles:
            break
        candidates = coverage_candidate_totals(core_ids, free, inputs, plan, pop_by_id)
        improving = [pair for pair in candidates if pair[0] < total - COVERAGE_EPSILON_MILES]
        if not improving:
            break
        best_id = min(improving)[1]
        core_ids = tuple(sorted((*core_ids, best_id)))
        grown = build_design_for_cores(core_ids, inputs, plan)
        # The winning candidate already passed evaluate_cores above, so its design builds.
        assert grown is not None
        design = grown
        free.remove(best_id)
    return design


def search_best_design(
    inputs: DesignInputs,
    params: DesignParams,
    plan: _SearchPlan,
) -> Design:
    """Build the strongest feasible design, then grow cores until demand is close.

    The core count is a floor, not an exact target. The search first finds the
    strongest feasible set at ``min_core_count`` (total last-mile only breaking ties),
    growing the tier one PoP at a time only if no feasible design exists at a size. It
    then adds cores past that floor while some aggregation is farther than
    ``core_coverage_target_miles`` from every core, each added core being the candidate
    that most shortens the aggregation-to-core haul -- so extra cores appear only where
    they bring demand closer. Enumerating each size must fit the share of RAM the search
    may use, or the design is refused rather than risk exhausting memory.
    """
    limit = enumeration_limit(total_memory_bytes(), params)
    base: Design | None = None
    max_size = len(plan.core_candidates)
    if params.max_core_count is not None:
        max_size = min(max_size, params.max_core_count)
    for size in range(params.min_core_count, max_size + 1):
        sets = core_combination_count(plan, size)
        if sets > limit:
            raise ValueError(
                f"Enumerating {sets} core sets of size {size} "
                f"exceeds the RAM budget of {limit}"
            )
        if sets == 0:
            continue
        logger.info(
            "Optimizing %d access sites; %d cores, %d required; %d core sets (limit %d)",
            len(inputs.access_vertices), size, len(plan.required_cores), sets, limit,
        )
        base = best_design_at_size(inputs, plan, size)
        if base is not None:
            logger.info("Feasible at %d cores; growing for coverage", len(base.core_ids))
            break
    if base is None:
        raise ValueError(f"No feasible design with at least {params.min_core_count} cores")
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    pop_by_id.update(plan.aggregations.twin_vertices)
    design = grow_cores_for_coverage(base, inputs, plan, params, pop_by_id)
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
    aggregations: _AggregationPlan,
    overrides: RoleOverrides,
    params: DesignParams,
) -> _SearchPlan:
    """Compute vertex strengths, access-vertex clusters, and core candidates.

    Required cores are the operator-forced cores. Operator-pinned aggregations are
    excluded from the free core candidates; since a forced installation's twin is an
    operator-pinned aggregation, installations are aggregation-only and never core
    candidates. Every other eligible PoP is a candidate, ranked nationally by strength.
    The operator's resolved forced-connection links ride along for the routing stage.
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
        params.tuning.cluster_radius_miles[0],
        params.tuning.cluster_radius_miles[1],
    )
    core_candidates = sorted(
        eligible_ids - aggregations.operator_forced,
        key=lambda pop_id: (-strength_by_id[pop_id], pop_id),
    )
    forced_links = replace(
        overrides.forced_links,
        required_cores=frozenset(overrides.forced_core_ids & eligible_ids),
    )
    return _SearchPlan(
        core_candidates,
        with_colocation_twins(aggregations, core_candidates, pop_by_id, inputs.adjacency),
        strength_by_id, clusters=clusters,
        core_backbone_min_degree=params.tuning.core_backbone_min_degree,
        forced_links=forced_links,
    )

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
    if params.min_core_count < 2:
        raise ValueError("min_core_count (the minimum number of cores) must be at least 2")
    if params.max_core_count is not None and params.max_core_count < params.min_core_count:
        raise ValueError("max_core_count must be at least min_core_count")
    if (
        params.max_core_count is not None
        and len(overrides.forced_core_ids) > params.max_core_count
    ):
        raise ValueError("more cores are forced than max_core_count allows")

    context = graph_context(vertices, physical_edges)
    operator_forced = overrides.forced_aggregation_ids
    aggregations = _AggregationPlan(operator_forced)
    eligible_ids = compute_eligible_ids(
        context.carrier_pops, roles, context.adjacency, params.allow_roadm_aggregation
    )
    eligible_ids = (
        eligible_ids | operator_forced | overrides.forced_core_ids
    ) - overrides.excluded_ids
    if len(eligible_ids) < max(2, params.min_core_count):
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
    plan = build_search_plan(inputs, eligible_ids, aggregations, overrides, params)
    if len(plan.core_candidates) < params.min_core_count:
        raise ValueError("Not enough reachable core candidates")
    return search_best_design(inputs, params, plan)
