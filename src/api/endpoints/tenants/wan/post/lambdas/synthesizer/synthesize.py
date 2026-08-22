from __future__ import annotations

import itertools
import logging
import math
import os
from dataclasses import replace

from synthesizer.input_graph import FiberSegment, Site
from synthesizer.model import (
    Synthesis,
    SynthesisInputs,
    SynthesisParams,
    RoleOverrides,
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

_SEARCH_LOG_INTERVAL = 50_000

CONVERGENCE_BACKBONE_DEGREE = 3


def compute_eligible_backbone_ids(
    carrier_pops: list[Site],
    adjacency: dict[str, list[tuple[str, float]]],
) -> set[str]:
    return {
        pop.id
        for pop in carrier_pops
        if len(adjacency.get(pop.id, [])) >= 2
    }


def convergence_promotion_ids(
    synthesis: Synthesis,
    min_degree: int = CONVERGENCE_BACKBONE_DEGREE,
) -> set[str]:
    counts: dict[str, int] = {}
    for left, right in synthesis.fiber_segment_keys:
        counts[left] = counts.get(left, 0) + 1
        counts[right] = counts.get(right, 0) + 1
    backbone = set(synthesis.backbone_ids)
    return {
        pop_id
        for pop_id, degree in counts.items()
        if degree >= min_degree and pop_id not in backbone
    }


def all_pairs_shortest(
    carrier_pops: list[Site],
    adjacency: dict[str, list[tuple[str, float]]],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, str]]]:
    all_distances: dict[str, dict[str, float]] = {}
    all_predecessors: dict[str, dict[str, str]] = {}
    for pop in carrier_pops:
        all_distances[pop.id], all_predecessors[pop.id] = dijkstra(adjacency, pop.id)
    return all_distances, all_predecessors


def validate_pop_graph(
    carrier_pops: list[Site],
    fiber_segments: dict[tuple[str, str], FiberSegment],
    adjacency: dict[str, list[tuple[str, float]]],
) -> None:
    pop_ids = {pop.id for pop in carrier_pops}
    physical_site_ids = {site_id for link in fiber_segments for site_id in link}
    if not pop_ids.issuperset(physical_site_ids):
        raise ValueError("Physical link graph references unknown Carrier PoP IDs")
    missing_pops = sorted(pop_ids - set(adjacency))
    if missing_pops:
        names = ", ".join(site.name for site in carrier_pops if site.id in missing_pops)
        raise ValueError(f"Carrier PoPs missing from physical link graph: {names}")


def backbone_set_strength(backbone_ids: tuple[str, ...], plan: _SearchPlan) -> float:
    return sum(plan.strength_by_id[backbone_id] for backbone_id in backbone_ids)


def free_backbone_candidates(plan: _SearchPlan) -> list[str]:
    return [
        pop_id for pop_id in plan.backbone_candidates if pop_id not in plan.required_backbone
    ]


def backbone_combination_count(plan: _SearchPlan, size: int) -> int:
    required = len(plan.required_backbone)
    if required > size:
        return 0
    return math.comb(len(free_backbone_candidates(plan)), size - required)


def backbone_combinations(plan: _SearchPlan, size: int) -> list[tuple[str, ...]]:
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
        access_paths = evaluate_backbone(backbone_set, inputs, plan)
        if access_paths is None:
            continue
        access_miles = sum(link.distance_miles for link in access_paths)
        key = (-strength, round(access_miles, 6))
        if best_key is None or key < best_key:
            best_set, best_key, best_strength = backbone_set, key, strength
            logger.info(
                "  set %d/%d: new best strength %.3f, last-mile %.0f mi",
                index, len(combos), strength, access_miles,
            )
    return best_set


def total_memory_bytes() -> int:
    configured_mb = os.environ.get("AWS_LAMBDA_FUNCTION_MEMORY_SIZE")
    if configured_mb:
        return int(configured_mb) * 1024 * 1024
    return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")


def enumeration_limit(memory_bytes: int, params: SynthesisParams) -> int:
    budget = params.tuning.search_memory_budget
    return int(memory_bytes * budget.memory_share / budget.bytes_per_combination)


def search_best_synthesis(
    inputs: SynthesisInputs,
    params: SynthesisParams,
    plan: _SearchPlan,
) -> Synthesis:
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
            "Synthesizing %d demand sites; %d backbone, %d required; %d sets (limit %d)",
            len(inputs.access_sites), size, len(plan.required_backbone), sets, limit,
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


def build_synthesis_inputs(
    sites: list[Site],
    fiber_segments: dict[tuple[str, str], FiberSegment],
) -> SynthesisInputs:
    carrier_pops = [site for site in sites if is_carrier_pop(site)]
    adjacency = build_adjacency(fiber_segments)
    validate_pop_graph(carrier_pops, fiber_segments, adjacency)
    all_distances, all_predecessors = all_pairs_shortest(carrier_pops, adjacency)
    return SynthesisInputs(
        access_sites=[site for site in sites if not is_carrier_pop(site)],
        carrier_pops=carrier_pops,
        fiber_segments=fiber_segments,
        eligible_backbone_ids=set(),
        adjacency=adjacency,
        all_distances=all_distances,
        all_predecessors=all_predecessors,
        carrier_blocks=biconnected_block_membership(adjacency),
    )


def build_search_plan(
    inputs: SynthesisInputs,
    eligible_ids: set[str],
    overrides: RoleOverrides,
    params: SynthesisParams,
    promoted_backbone_ids: frozenset[str] = frozenset(),
) -> _SearchPlan:
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
    sites: list[Site],
    fiber_segments: dict[tuple[str, str], FiberSegment],
    params: SynthesisParams,
    overrides: RoleOverrides | None = None,
) -> Synthesis:
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

    graph = build_synthesis_inputs(sites, fiber_segments)
    eligible_ids = compute_eligible_backbone_ids(
        graph.carrier_pops, graph.adjacency
    )
    eligible_ids = eligible_ids | overrides.forced_backbone_ids
    backbone_eligible_ids = eligible_ids - overrides.prohibited_backbone_ids
    if len(backbone_eligible_ids) < max(2, params.min_backbone_count):
        raise ValueError("Not enough eligible Carrier backbone PoPs (degree >= 2)")

    inputs = replace(graph, eligible_backbone_ids=backbone_eligible_ids)
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
        new = convergence_promotion_ids(synthesis) - promoted
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
