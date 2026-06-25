"""Synthesize a two-tier backbone/demand WAN over the carrier graph.

Backbone nodes are chosen for strength, not mileage (the source mapbook has no
distances): each node's strength is its degree plus compass spread plus path
straightness, and the strongest feasible set of at least the configured
``min_backbone_count`` wins, with total last-mile only breaking ties. The backbone
then grows past that floor while any demand vertex is farther than
``backbone_coverage_target_miles`` from every selected backbone node, each added node
being the one that most shortens the demand-to-backbone haul -- so extra backbone
nodes appear only where they bring demand closer, never as a mileage cost minimized
over candidate sets.

Eligibility is gated twice: a carrier PoP may serve as a backbone node only if it has
at least two physical links AND sits at a data-center city (a colocation provider
operates a cage there). The operator's forced backbone pins are gated the same way
(in ``synthesizer.overrides``).

Every demand vertex (a unified tenant site or CSP region) homes to its
``access_backbone_links`` nearest selected backbone nodes over vertex-disjoint paths.
On top of the algorithm, the operator may pin roles by PoP name (``RoleOverrides``,
resolved by ``apply_role_overrides``): force a PoP onto the backbone, or exclude it
from it.
"""

from __future__ import annotations

import itertools
import logging
import math
import os
from dataclasses import dataclass, replace

from synthesizer.input_graph import PhysicalEdge, Vertex, haversine_miles
from synthesizer.model import (
    AccessEdge,
    Design,
    DesignInputs,
    DesignMetrics,
    DesignParams,
    PathUse,
    RoleOverrides,
    is_carrier_pop,
)
from synthesizer.forced import (
    apply_forced_access_homes,
    removed_backbone_pairs,
)
from synthesizer.graphs import (
    build_adjacency,
    dijkstra,
    vertex_disjoint_paths_to_cores,
    path_edge_keys,
)
from synthesizer.backbone import BackboneConstraints, backbone_mesh_paths
from synthesizer.search_plan import _SearchPlan
from synthesizer.strength import backbone_strength

logger = logging.getLogger(__name__)

# How often the backbone-set scan logs a progress heartbeat. A single size can
# enumerate millions of sets; without this the scan goes silent between "new best"
# lines.
_SEARCH_LOG_INTERVAL = 50_000


@dataclass
class _DesignDraft:
    access_edges: list[AccessEdge]
    path_uses: list[PathUse]


def finalize_design(
    backbone_ids: tuple[str, ...],
    draft: _DesignDraft,
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> Design:
    """Compute edge sets, mileage estimate, and score for a design draft."""
    physical_edge_keys: set[tuple[str, str]] = set()
    for path_use in draft.path_uses:
        physical_edge_keys.update(path_edge_keys(path_use.path))

    access_miles = sum(edge.distance_miles for edge in draft.access_edges)
    physical_miles = sum(
        physical_edges[key].distance_miles for key in physical_edge_keys
    )
    score = access_miles + physical_miles
    carrier_on_paths = {vertex_id for use in draft.path_uses for vertex_id in use.path}
    transit_ids = tuple(sorted(carrier_on_paths - set(backbone_ids)))
    return Design(
        backbone_ids=backbone_ids,
        transit_ids=transit_ids,
        access_edges=draft.access_edges,
        physical_edge_keys=physical_edge_keys,
        path_uses=draft.path_uses,
        metrics=DesignMetrics(score, access_miles, physical_miles),
    )


def backbone_has_mesh_peers(
    backbone_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    mesh_degree: int,
) -> bool:
    """True if every backbone node can reach enough peers to wire its mesh links."""
    target = min(mesh_degree, len(backbone_ids) - 1)
    return all(
        sum(
            1
            for right in backbone_ids
            if right != left and math.isfinite(all_distances[left].get(right, math.inf))
        )
        >= target
        for left in backbone_ids
    )


def demand_homes(
    demand_id: str,
    backbone_ids: tuple[str, ...],
    homes: int,
    inputs: DesignInputs,
    cache: dict[tuple[str, tuple[str, ...], int], bool],
) -> bool:
    """True if the demand vertex reaches ``homes`` distinct backbone nodes disjointly.

    A single vertex-disjoint max-flow over the whole backbone set finds up to
    ``homes`` paths to distinct backbone nodes, so this answers feasibility for any
    homing degree. Memoized per (demand vertex, backbone set, degree).
    """
    key = (demand_id, backbone_ids, homes)
    cached = cache.get(key)
    if cached is None:
        _cost, paths = vertex_disjoint_paths_to_cores(
            inputs.adjacency, demand_id, backbone_ids, homes
        )
        cached = len(paths) >= homes
        cache[key] = cached
    return cached


def nearest_pop_id(access: Vertex, carrier_pops: list[Vertex]) -> str:
    """Id of the Carrier PoP nearest to an access site."""
    return min(carrier_pops, key=lambda pop: haversine_miles(access, pop)).id


def assign_access(
    backbone_ids: tuple[str, ...],
    inputs: DesignInputs,
    plan: _SearchPlan,
) -> list[AccessEdge] | None:
    """Home every demand vertex to its nearest backbone nodes in a single pass.

    Each demand vertex (a unified tenant site or CSP region) homes to its
    ``plan.tuning.access_backbone_links`` nearest selected backbone nodes, ranked by
    great-circle distance, with any operator-forced access-backbone link leading its
    homes regardless of distance. The same code path serves tenant and CSP demand --
    they differ only by source kind at output time. Returns the access edges, or None
    when the backbone is smaller than the configured number of homes (no vertex could
    reach that many distinct nodes).
    """
    links = plan.tuning.access_backbone_links
    backbone_set = set(backbone_ids)
    if len(backbone_set) < links:
        return None
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    access_edges: list[AccessEdge] = []
    for access in inputs.access_vertices:
        completed = [
            backbone_id
            for _distance, backbone_id in sorted(
                (haversine_miles(access, pop_by_id[backbone_id]), backbone_id)
                for backbone_id in backbone_set
            )
        ][:links]
        completed = apply_forced_access_homes(
            access, completed, plan.forced_links, pop_by_id, links
        )
        access_edges.extend(
            AccessEdge(
                access.id, backbone_id,
                haversine_miles(access, pop_by_id[backbone_id]),
            )
            for backbone_id in completed
        )
    return access_edges


def demand_can_home(
    backbone_ids: tuple[str, ...],
    inputs: DesignInputs,
    plan: _SearchPlan,
) -> bool:
    """True if every demand vertex reaches the required backbone nodes disjointly.

    Vertex-disjoint redundancy is what the validation later enforces, so a backbone
    set is only feasible when every demand vertex can reach
    ``plan.tuning.access_backbone_links`` distinct backbone nodes over disjoint paths.
    """
    homes = plan.tuning.access_backbone_links
    return all(
        demand_homes(access.id, backbone_ids, homes, inputs, plan.feasibility_cache)
        for access in inputs.access_vertices
    )


def evaluate_backbone(
    backbone_ids: tuple[str, ...],
    inputs: DesignInputs,
    plan: _SearchPlan,
) -> list[AccessEdge] | None:
    """Score a backbone set's feasibility and demand homing without routing paths.

    Returns None when a node cannot reach enough peers to wire its mesh links or some
    demand vertex cannot reach its backbone nodes. Routed paths are deferred to the
    winning set, since they do not affect the strength ranking.
    """
    if not backbone_has_mesh_peers(
        backbone_ids, inputs.all_distances, plan.tuning.backbone_mesh_degree
    ):
        return None
    if not demand_can_home(backbone_ids, inputs, plan):
        return None
    return assign_access(backbone_ids, inputs, plan)


def routed_path_uses(
    backbone_ids: tuple[str, ...],
    inputs: DesignInputs,
    plan: _SearchPlan,
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> list[PathUse]:
    """Reconstruct the backbone-mesh paths for a design."""
    backbone_set = set(backbone_ids)
    constraints = BackboneConstraints(
        removed_backbone_pairs(backbone_set, plan.forced_links),
        mesh_degree=plan.tuning.backbone_mesh_degree,
    )
    return backbone_mesh_paths(
        backbone_ids, inputs.all_distances, inputs.all_predecessors, physical_edges, constraints
    )


def build_design_for_backbone(
    backbone_ids: tuple[str, ...],
    inputs: DesignInputs,
    plan: _SearchPlan,
) -> Design | None:
    """Assemble a full two-tier design for one fixed set of backbone PoPs.

    Returns None if a node cannot reach enough peers to wire its mesh links or some
    demand vertex cannot reach its backbone nodes.
    """
    access_edges = evaluate_backbone(backbone_ids, inputs, plan)
    if access_edges is None:
        return None
    path_uses = routed_path_uses(backbone_ids, inputs, plan, inputs.physical_edges)
    draft = _DesignDraft(access_edges, path_uses)
    return finalize_design(backbone_ids, draft, inputs.physical_edges)


def compute_eligible_backbone_ids(
    carrier_pops: list[Vertex],
    adjacency: dict[str, list[tuple[str, float]]],
    datacenter_cities: frozenset[tuple[str, str]],
) -> set[str]:
    """Carrier PoPs that may serve as backbone nodes.

    A PoP needs at least two physical links to ever route redundantly, so degree-one
    PoPs (spurs) are excluded. It must also sit at a data-center city -- a colocation
    provider operates a cage there -- because the backbone is built from carrier PoPs
    that can be lit at a provider facility; a PoP off every data-center city is never
    eligible, no matter how strong.
    """
    return {
        pop.id
        for pop in carrier_pops
        if len(adjacency.get(pop.id, [])) >= 2
        and (pop.info.municipality, pop.info.state) in datacenter_cities
    }


def all_pairs_shortest(
    carrier_pops: list[Vertex],
    adjacency: dict[str, list[tuple[str, float]]],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, str]]]:
    """Run Dijkstra from every Carrier PoP for reuse across backbone sets."""
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


def backbone_set_strength(backbone_ids: tuple[str, ...], plan: _SearchPlan) -> float:
    """Total strength of a backbone set: the primary objective the search maximizes."""
    return sum(plan.strength_by_id[backbone_id] for backbone_id in backbone_ids)


def free_backbone_candidates(plan: _SearchPlan) -> list[str]:
    """Backbone candidates the search may choose freely, excluding required nodes."""
    return [
        pop_id for pop_id in plan.backbone_candidates if pop_id not in plan.required_backbone
    ]


def backbone_combination_count(plan: _SearchPlan, size: int) -> int:
    """How many backbone sets of ``size`` exist once required nodes are fixed in."""
    required = len(plan.required_backbone)
    if required > size:
        return 0
    return math.comb(len(free_backbone_candidates(plan)), size - required)


def backbone_combinations(plan: _SearchPlan, size: int) -> list[tuple[str, ...]]:
    """Every ``size``-node set, with the required backbone nodes fixed into each one."""
    required = tuple(sorted(plan.required_backbone))
    if len(required) > size:
        return []
    free = free_backbone_candidates(plan)
    return [
        required + extra
        for extra in itertools.combinations(free, size - len(required))
    ]


def best_design_at_size(
    inputs: DesignInputs,
    plan: _SearchPlan,
    size: int,
) -> Design | None:
    """Strongest feasible design using exactly ``size`` backbone nodes, or None.

    Any operator-forced backbone nodes are fixed into every candidate set; the rest
    are chosen by strength (the spec forbids mileage as a design cost), with total
    last-mile only breaking ties among equally strong sets. Backbone sets are tried
    strongest-first and scored cheaply (feasibility plus demand homing, no routed
    paths). Because strength is non-increasing down that order, the moment a feasible
    set is in hand the search stops as soon as a candidate is strictly weaker. Routed
    paths are reconstructed only for the winning set.
    """
    combos = sorted(
        backbone_combinations(plan, size),
        key=lambda combo: -backbone_set_strength(combo, plan),
    )
    logger.info("Evaluating %d backbone sets of size %d, strongest first", len(combos), size)
    best_set: tuple[str, ...] | None = None
    best_key: tuple[float, float] | None = None
    best_strength = -math.inf
    for index, backbone_set in enumerate(combos, start=1):
        if index % _SEARCH_LOG_INTERVAL == 0:
            logger.info("  scanned %d/%d backbone sets", index, len(combos))
        strength = backbone_set_strength(backbone_set, plan)
        if strength < best_strength:
            logger.info("  strongest feasible backbone locked at set %d/%d", index, len(combos))
            break
        access_edges = evaluate_backbone(backbone_set, inputs, plan)
        if access_edges is None:
            continue
        access_miles = sum(edge.distance_miles for edge in access_edges)
        key = (-strength, round(access_miles, 6))
        if best_key is None or key < best_key:
            best_set, best_key, best_strength = backbone_set, key, strength
            logger.info(
                "  set %d/%d: new best strength %.3f, last-mile %.0f mi",
                index, len(combos), strength, access_miles,
            )
    if best_set is None:
        return None
    return build_design_for_backbone(best_set, inputs, plan)


def total_memory_bytes() -> int:
    """Physical RAM installed on this machine, in bytes (portable across OSes)."""
    return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")


def enumeration_limit(memory_bytes: int, params: DesignParams) -> int:
    """How many backbone sets fit in the share of RAM the enumeration may use."""
    budget = params.tuning.enum_budget
    return int(memory_bytes * budget.memory_fraction / budget.set_peak_bytes)


COVERAGE_EPSILON_MILES = 1.0  # a new backbone node must cut total demand haul by this


def demand_haul_miles(
    backbone_ids: tuple[str, ...],
    access_vertices: list[Vertex],
    pop_by_id: dict[str, Vertex],
) -> tuple[float, float]:
    """The worst and total straight-line miles from demand to its nearest backbone node.

    The coverage signal the search drives down by adding backbone nodes: ``worst`` is
    the long-haul an operator sees on the map; ``total`` lets one added node show
    progress even while another still-distant demand vertex dominates the worst.
    """
    nodes = [pop_by_id[backbone_id] for backbone_id in backbone_ids]
    distances = [
        min(haversine_miles(access, node) for node in nodes)
        for access in access_vertices
    ]
    return max(distances, default=0.0), sum(distances)


def coverage_candidate_totals(
    backbone_ids: tuple[str, ...],
    free: list[str],
    inputs: DesignInputs,
    plan: _SearchPlan,
    pop_by_id: dict[str, Vertex],
) -> list[tuple[float, str]]:
    """Each free candidate's total demand-to-backbone haul once it joins the backbone.

    Infeasible additions (a candidate whose promotion strands demand) are dropped, so
    every returned pair is a buildable grown set ranked by how short it leaves the haul.
    """
    totals: list[tuple[float, str]] = []
    for candidate_id in free:
        candidate_set = tuple(sorted((*backbone_ids, candidate_id)))
        if evaluate_backbone(candidate_set, inputs, plan) is None:
            continue
        _worst, total = demand_haul_miles(candidate_set, inputs.access_vertices, pop_by_id)
        totals.append((total, candidate_id))
    return totals


def grow_backbone_for_coverage(
    base: Design,
    inputs: DesignInputs,
    plan: _SearchPlan,
    params: DesignParams,
    pop_by_id: dict[str, Vertex],
) -> Design:
    """Add backbone nodes beyond the strength-chosen base until demand is close enough.

    While some demand vertex is farther than ``backbone_coverage_target_miles`` from
    every selected backbone node, add the one remaining candidate that most reduces the
    total demand-to-backbone haul, rebuilding the design around it. Extra nodes are thus
    coverage-driven: strength still chooses the base backbone, and the operator's
    coverage target is a constraint on how far the backbone may leave demand, not a
    mileage cost minimized over candidate sets. Growth stops once every demand vertex is
    within target, the backbone reaches ``max_backbone_count``, no remaining candidate
    brings demand meaningfully closer, or the candidates are exhausted.
    """
    target_miles = params.tuning.backbone_coverage_target_miles
    backbone_ids = base.backbone_ids
    design = base
    free = [pop_id for pop_id in plan.backbone_candidates if pop_id not in backbone_ids]
    logger.info(
        "Growing backbone for coverage: %d candidates, %.0f mi target", len(free), target_miles
    )
    while free:
        if params.max_backbone_count is not None and len(backbone_ids) >= params.max_backbone_count:
            logger.info("Coverage growth stopped at the %d-node cap", len(backbone_ids))
            break
        worst, total = demand_haul_miles(backbone_ids, inputs.access_vertices, pop_by_id)
        if worst <= target_miles:
            logger.info("Coverage met at %d nodes (worst haul %.0f mi)", len(backbone_ids), worst)
            break
        logger.info(
            "Coverage round at %d nodes: worst haul %.0f mi > %.0f target; scoring %d candidates",
            len(backbone_ids), worst, target_miles, len(free),
        )
        candidates = coverage_candidate_totals(backbone_ids, free, inputs, plan, pop_by_id)
        improving = [pair for pair in candidates if pair[0] < total - COVERAGE_EPSILON_MILES]
        if not improving:
            logger.info("No candidate improves coverage; holding at %d nodes", len(backbone_ids))
            break
        best_id = min(improving)[1]
        backbone_ids = tuple(sorted((*backbone_ids, best_id)))
        grown = build_design_for_backbone(backbone_ids, inputs, plan)
        # The winning candidate already passed evaluate_backbone above, so its design builds.
        assert grown is not None
        design = grown
        free.remove(best_id)
        logger.info("Added node %s for coverage; now %d nodes", best_id, len(backbone_ids))
    return design


def search_best_design(
    inputs: DesignInputs,
    params: DesignParams,
    plan: _SearchPlan,
) -> Design:
    """Build the strongest feasible design, then grow the backbone until demand is close.

    The backbone count is a floor, not an exact target. The search first finds the
    strongest feasible set at ``min_backbone_count`` (total last-mile only breaking
    ties), growing the backbone one PoP at a time only if no feasible design exists at a
    size. It then adds nodes past that floor while some demand vertex is farther than
    ``backbone_coverage_target_miles`` from every selected node, each added node being
    the candidate that most shortens the demand-to-backbone haul -- so extra nodes appear
    only where they bring demand closer. Enumerating each size must fit the share of RAM
    the search may use, or the design is refused rather than risk exhausting memory.
    """
    limit = enumeration_limit(total_memory_bytes(), params)
    base: Design | None = None
    max_size = len(plan.backbone_candidates)
    if params.max_backbone_count is not None:
        max_size = min(max_size, params.max_backbone_count)
    for size in range(params.min_backbone_count, max_size + 1):
        sets = backbone_combination_count(plan, size)
        if sets > limit:
            raise ValueError(
                f"Enumerating {sets} backbone sets of size {size} "
                f"exceeds the RAM budget of {limit}"
            )
        if sets == 0:
            continue
        logger.info(
            "Synthesizing %d demand vertices; %d backbone, %d required; %d sets (limit %d)",
            len(inputs.access_vertices), size, len(plan.required_backbone), sets, limit,
        )
        base = best_design_at_size(inputs, plan, size)
        if base is not None:
            logger.info("Feasible at %d nodes; growing for coverage", len(base.backbone_ids))
            break
    if base is None:
        raise ValueError(
            f"No feasible design with at least {params.min_backbone_count} backbone nodes"
        )
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    design = grow_backbone_for_coverage(base, inputs, plan, params, pop_by_id)
    logger.info("Selected a %d-node backbone design", len(design.backbone_ids))
    return design


@dataclass(frozen=True)
class _GraphContext:
    """Vertex partition and precomputed shortest-path context shared across backbone sets."""

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
    adjacency = build_adjacency(physical_edges)
    validate_pop_graph(carrier_pops, physical_edges, adjacency)
    all_distances, all_predecessors = all_pairs_shortest(carrier_pops, adjacency)
    return _GraphContext(carrier_pops, all_access, adjacency, all_distances, all_predecessors)


def build_search_plan(
    inputs: DesignInputs,
    eligible_ids: set[str],
    overrides: RoleOverrides,
    params: DesignParams,
) -> _SearchPlan:
    """Compute vertex strengths and backbone candidates.

    Required backbone nodes are the operator-forced backbone nodes. Every eligible PoP
    is a backbone candidate, ranked nationally by strength. The operator's resolved
    forced-connection links ride along for the routing stage.
    """
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    max_degree = max((len(inputs.adjacency[pop_id]) for pop_id in eligible_ids), default=1)
    strength_by_id = {
        pop_id: backbone_strength(
            pop_id, inputs, pop_by_id, max_degree, params.tuning.compass_octants
        )
        for pop_id in eligible_ids
    }
    backbone_candidates = sorted(
        eligible_ids,
        key=lambda pop_id: (-strength_by_id[pop_id], pop_id),
    )
    forced_links = replace(
        overrides.forced_links,
        required_backbone=frozenset(overrides.forced_backbone_ids & eligible_ids),
    )
    return _SearchPlan(
        backbone_candidates,
        strength_by_id,
        tuning=params.tuning,
        forced_links=forced_links,
    )


def synthesize_two_tier_design(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    params: DesignParams,
    overrides: RoleOverrides | None = None,
) -> Design:
    """Synthesize a two-tier WAN over the Carrier graph for the given parameters.

    ``overrides`` carries operator role pins already resolved to vertex ids; pass
    ``None`` for an unpinned design.
    """
    overrides = overrides if overrides is not None else RoleOverrides()
    if params.min_backbone_count < 2:
        raise ValueError(
            "min_backbone_count (the minimum number of backbone nodes) must be at least 2"
        )
    if (
        params.max_backbone_count is not None
        and params.max_backbone_count < params.min_backbone_count
    ):
        raise ValueError("max_backbone_count must be at least min_backbone_count")
    if (
        params.max_backbone_count is not None
        and len(overrides.forced_backbone_ids) > params.max_backbone_count
    ):
        raise ValueError("more backbone nodes are forced than max_backbone_count allows")

    context = graph_context(vertices, physical_edges)
    eligible_ids = compute_eligible_backbone_ids(
        context.carrier_pops, context.adjacency, params.datacenter_cities
    )
    eligible_ids = eligible_ids | overrides.forced_backbone_ids
    backbone_eligible_ids = eligible_ids - overrides.prohibited_backbone_ids
    if len(backbone_eligible_ids) < max(2, params.min_backbone_count):
        raise ValueError(
            "Not enough eligible Carrier backbone PoPs (degree >= 2 at a data-center city)"
        )

    inputs = DesignInputs(
        access_vertices=context.all_access,
        carrier_pops=context.carrier_pops,
        physical_edges=physical_edges,
        eligible_backbone_ids=backbone_eligible_ids,
        adjacency=context.adjacency,
        all_distances=context.all_distances,
        all_predecessors=context.all_predecessors,
    )
    plan = build_search_plan(inputs, backbone_eligible_ids, overrides, params)
    return search_best_design(inputs, params, plan)
