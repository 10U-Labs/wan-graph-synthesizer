"""Synthesize a two-tier backbone/demand WAN over the carrier graph.

Backbone nodes are chosen for strength, not mileage (the source mapbook has no
distances): each node's strength is how many diverse paths its fiber can carry plus
compass spread plus path straightness, and the strongest feasible set of at least the
configured ``min_backbone_count`` wins, with total last-mile only breaking ties. The
backbone then grows past that floor while any demand vertex is farther than
``backbone_coverage_target_miles`` from every selected backbone node, each added node
being the one that leaves the demand hauls shortest read worst-first -- so extra backbone
nodes appear only where they bring demand closer, never as a mileage cost minimized
over candidate sets.

A final convergence pass then promotes natural hubs: any data-center city where at least
``CONVERGENCE_BACKBONE_DEGREE`` of the synthesis's own drawn fiber lines meet is forced
into the backbone and the synthesis is recomputed, repeating until a redraw finds no new
hub. The count is per-synthesis (this synthesis's used physical edges), not the shared carrier
substrate's degree, so a city that hubs one tenant need not hub another.

Eligibility is gated twice: a carrier PoP may serve as a backbone node only if it has
at least two physical links AND sits at a data-center city (a colocation provider
operates a cage there). The operator's forced backbone pins are gated the same way
(in ``synthesizer.overrides``).

Every demand vertex (a unified tenant site or provider region) homes to its
``access_backbone_links`` nearest selected backbone nodes. There is no last-mile fiber
data, so a home is the logical link from a demand vertex to a backbone node, not a
path over fiber -- the only requirement is that enough backbone nodes exist to home to.
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

from synthesizer.input_graph import PhysicalEdge, Vertex
from synthesizer.model import (
    Synthesis,
    SynthesisInputs,
    SynthesisParams,
    RoleOverrides,
    backbone_city_allowed,
    is_carrier_pop,
)
from synthesizer.graphs import (
    biconnected_block_membership,
    build_adjacency,
    dijkstra,
)
from synthesizer.assemble import evaluate_backbone, forced_backbone_resilience_error
from synthesizer.coverage import grow_backbone_for_coverage
from synthesizer.search_plan import _SearchPlan
from synthesizer.strength import backbone_strength, diverse_path_bounds

logger = logging.getLogger(__name__)

# How often the backbone-set scan logs a progress heartbeat. A single size can
# enumerate millions of sets; without this the scan goes silent between "new best"
# lines.
_SEARCH_LOG_INTERVAL = 50_000

# A carrier PoP where at least this many of the synthesis's own drawn fiber lines converge
# is a natural hub; if it also sits at a data-center city it is promoted into the backbone
# and the synthesis is recomputed (GitHub issue #4). The count is per-synthesis (the synthesis's
# used physical edges), never the shared carrier substrate's degree.
CONVERGENCE_BACKBONE_DEGREE = 3




def compute_eligible_backbone_ids(
    carrier_pops: list[Vertex],
    adjacency: dict[str, list[tuple[str, float]]],
    datacenter_cities: frozenset[tuple[str, str]] | None,
) -> set[str]:
    """Carrier PoPs that may serve as backbone nodes.

    A PoP needs at least two physical links to ever path redundantly, so degree-one
    PoPs (spurs) are excluded regardless of policy. It must also sit at a data-center
    city -- a colocation provider operates a cage there -- because the backbone is built
    from carrier PoPs that can be lit at a provider facility; a PoP off every data-center
    city is never eligible, no matter how strong. When ``datacenter_cities`` is ``None``
    (the operator's free-for-all) the city gate is lifted and any degree-two carrier PoP
    is eligible.
    """
    return {
        pop.id
        for pop in carrier_pops
        if len(adjacency.get(pop.id, [])) >= 2
        and backbone_city_allowed(pop.info, datacenter_cities)
    }


def convergence_promotion_ids(
    synthesis: Synthesis,
    carrier_pops: list[Vertex],
    datacenter_cities: frozenset[tuple[str, str]] | None,
    min_degree: int = CONVERGENCE_BACKBONE_DEGREE,
) -> set[str]:
    """Non-backbone carrier PoPs at a data-center city where this synthesis's fiber converges.

    A PoP qualifies when at least ``min_degree`` of *this synthesis's* drawn physical edges
    meet at it. The count comes from ``synthesis.physical_edge_keys`` -- the fiber actually
    drawn for this synthesis -- so the measure is per-synthesis, never the shared substrate's
    degree. A non-backbone carrier PoP only ever carries those edges as a transit node
    (demand homes to backbone nodes, never to transit), so its incident count is exactly
    the number of the synthesis's lines meeting there. PoPs already seated in the backbone
    are excluded; the caller forces the rest in and redraws. When ``datacenter_cities``
    is ``None`` (the operator's free-for-all) the data-center-city gate is lifted, so any
    non-backbone convergence hub promotes.
    """
    counts: dict[str, int] = {}
    for left, right in synthesis.physical_edge_keys:
        counts[left] = counts.get(left, 0) + 1
        counts[right] = counts.get(right, 0) + 1
    backbone = set(synthesis.backbone_ids)
    pop_by_id = {pop.id: pop for pop in carrier_pops}
    return {
        pop_id
        for pop_id, degree in counts.items()
        if degree >= min_degree
        and pop_id not in backbone
        and backbone_city_allowed(pop_by_id[pop_id].info, datacenter_cities)
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


def best_backbone_at_size(
    inputs: SynthesisInputs,
    plan: _SearchPlan,
    size: int,
) -> tuple[str, ...] | None:
    """The seats of the strongest feasible backbone of exactly ``size`` nodes, or None.

    Any operator-forced backbone nodes are fixed into every candidate set; the rest
    are chosen by strength (the spec forbids mileage as a synthesis cost), with total
    last-mile only breaking ties among equally strong sets. Backbone sets are tried
    strongest-first and scored cheaply (feasibility plus demand homing, no paths
    drawn). Because strength is non-increasing down that order, the moment a feasible
    set is in hand the search stops as soon as a candidate is strictly weaker.

    Seats come back rather than a synthesis because nothing here needs one. Coverage growth
    reads the seats and rebuilds over whatever it settles on, so a synthesis drawn here is
    thrown away the moment a node is seated past this size -- 234 of DOW's 438 seconds,
    which is what put that tenant past the fifteen minutes AWS allows a Lambda (GitHub
    issue #72). Feasibility does not need one either: ``build_synthesis_for_backbone``
    returns ``None`` in exactly the case ``evaluate_backbone`` does, and every candidate
    set below has already been through ``evaluate_backbone``.
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
    return best_set


def total_memory_bytes() -> int:
    """The memory available to this process, in bytes.

    On Lambda, honor ``AWS_LAMBDA_FUNCTION_MEMORY_SIZE`` (the function's configured limit,
    in MB) -- ``sysconf`` would report the host's RAM, far more than the function actually
    has, and oversize the backbone enumeration into an OOM kill. Off Lambda (local, tests),
    fall back to the installed physical RAM.
    """
    configured_mb = os.environ.get("AWS_LAMBDA_FUNCTION_MEMORY_SIZE")
    if configured_mb:
        return int(configured_mb) * 1024 * 1024
    return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")


def enumeration_limit(memory_bytes: int, params: SynthesisParams) -> int:
    """How many backbone sets fit in the share of RAM the enumeration may use."""
    budget = params.tuning.search_memory_budget
    return int(memory_bytes * budget.memory_share / budget.bytes_per_combination)




def search_best_synthesis(
    inputs: SynthesisInputs,
    params: SynthesisParams,
    plan: _SearchPlan,
) -> Synthesis:
    """Build the strongest feasible synthesis, then grow the backbone until demand is close.

    The backbone count is a floor, not an exact target. The search first finds the
    strongest feasible set at ``min_backbone_count`` (total last-mile only breaking
    ties), growing the backbone one PoP at a time only if no feasible synthesis exists at a
    size. It then adds nodes past that floor while some demand vertex is farther than
    ``backbone_coverage_target_miles`` from every selected node, each added node being the
    best-connected candidate that brings those distances inside the target -- so extra
    nodes appear only where they close a gap, and the one seated is chosen for the fiber
    it can carry rather than the miles it saves. Enumerating each size must fit
    the share of RAM
    the search may use, or the synthesis is refused rather than risk exhausting memory.
    """
    limit = enumeration_limit(total_memory_bytes(), params)
    base: tuple[str, ...] | None = None
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
        base = best_backbone_at_size(inputs, plan, size)
        if base is not None:
            logger.info("Feasible at %d nodes; growing for coverage", len(base))
            break
    if base is None:
        raise ValueError(
            f"No feasible synthesis with at least {params.min_backbone_count} backbone nodes"
        )
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    synthesis = grow_backbone_for_coverage(base, inputs, plan, params, pop_by_id)
    logger.info("Selected a %d-node backbone synthesis", len(synthesis.backbone_ids))
    return synthesis


@dataclass(frozen=True)
class SearchGraph:
    """The graph every candidate backbone set is scored against.

    The vertices split into carrier PoPs and access sites, the fiber between the PoPs, and
    the shortest paths and biconnected blocks computed over it once for the whole run.
    """

    carrier_pops: list[Vertex]
    all_access: list[Vertex]
    adjacency: dict[str, list[tuple[str, float]]]
    all_distances: dict[str, dict[str, float]]
    all_predecessors: dict[str, dict[str, str]]
    carrier_blocks: dict[str, frozenset[int]]


def build_search_graph(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> SearchGraph:
    """Split the vertices into PoPs and access sites and precompute the shared graph."""
    carrier_pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    all_access = [vertex for vertex in vertices if not is_carrier_pop(vertex)]
    adjacency = build_adjacency(physical_edges)
    validate_pop_graph(carrier_pops, physical_edges, adjacency)
    all_distances, all_predecessors = all_pairs_shortest(carrier_pops, adjacency)
    return SearchGraph(
        carrier_pops, all_access, adjacency, all_distances, all_predecessors,
        biconnected_block_membership(adjacency),
    )


def build_search_plan(
    inputs: SynthesisInputs,
    eligible_ids: set[str],
    overrides: RoleOverrides,
    params: SynthesisParams,
    promoted_backbone_ids: frozenset[str] = frozenset(),
) -> _SearchPlan:
    """Compute vertex strengths and backbone candidates.

    Required backbone nodes are the operator-forced backbone nodes plus any
    ``promoted_backbone_ids`` the convergence pass has fixed in (already eligible by
    construction). Every eligible PoP is a backbone candidate, ranked nationally by
    strength. The operator's resolved forced-connection links ride along for the
    routing stage. The nodes the diverse path count is not asked of do not: the exemption is
    validation's, and the handler carries it there itself.
    """
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    bounds = diverse_path_bounds(eligible_ids, inputs.adjacency)
    strength_by_id = {
        pop_id: backbone_strength(
            pop_id, inputs, pop_by_id, bounds, params.tuning.compass_sector_count
        )
        for pop_id in eligible_ids
    }
    backbone_candidates = sorted(
        eligible_ids,
        key=lambda pop_id: (-strength_by_id[pop_id], pop_id),
    )
    required = (overrides.forced_backbone_ids & eligible_ids) | promoted_backbone_ids
    forced_links = replace(
        overrides.forced_links,
        required_backbone=frozenset(required),
    )
    return _SearchPlan(
        backbone_candidates,
        strength_by_id,
        tuning=params.tuning,
        forced_links=forced_links,
        seat_cap=params.max_backbone_count,
    )


def synthesize_two_tier(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    params: SynthesisParams,
    overrides: RoleOverrides | None = None,
) -> Synthesis:
    """Synthesize a two-tier WAN over the Carrier graph for the given parameters.

    ``overrides`` carries operator role pins already resolved to vertex ids; pass
    ``None`` for an unpinned synthesis.
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

    graph = build_search_graph(vertices, physical_edges)
    eligible_ids = compute_eligible_backbone_ids(
        graph.carrier_pops, graph.adjacency, params.datacenter_cities
    )
    eligible_ids = eligible_ids | overrides.forced_backbone_ids
    backbone_eligible_ids = eligible_ids - overrides.prohibited_backbone_ids
    if len(backbone_eligible_ids) < max(2, params.min_backbone_count):
        raise ValueError(
            "Not enough eligible Carrier backbone PoPs (degree >= 2"
            + (" at a data-center city)" if params.datacenter_cities is not None else ")")
        )

    inputs = SynthesisInputs(
        access_vertices=graph.all_access,
        carrier_pops=graph.carrier_pops,
        physical_edges=physical_edges,
        eligible_backbone_ids=backbone_eligible_ids,
        adjacency=graph.adjacency,
        all_distances=graph.all_distances,
        all_predecessors=graph.all_predecessors,
        carrier_blocks=graph.carrier_blocks,
    )
    forced_base = overrides.forced_backbone_ids & backbone_eligible_ids
    promoted: frozenset[str] = frozenset()
    while True:
        plan = build_search_plan(
            inputs, backbone_eligible_ids, overrides, params, promoted
        )
        forced_error = forced_backbone_resilience_error(
            plan.required_backbone, inputs, max(2, params.min_backbone_count)
        )
        if forced_error is not None:
            raise ValueError(forced_error)
        synthesis = search_best_synthesis(inputs, params, plan)

        if not params.promote_high_degree_convergences:
            return synthesis
        new = convergence_promotion_ids(
            synthesis, inputs.carrier_pops, params.datacenter_cities
        ) - promoted
        if not new:
            return synthesis
        grown = promoted | new
        if (
            params.max_backbone_count is not None
            and len(forced_base | grown) > params.max_backbone_count
        ):
            logger.info(
                "Convergence promotion stopped at the %d-node cap; %d data-center "
                "crossing(s) left as transit",
                params.max_backbone_count, len(new),
            )
            return synthesis
        logger.info("Promoting %d data-center convergence hub(s); redrawing", len(new))
        promoted = grown
