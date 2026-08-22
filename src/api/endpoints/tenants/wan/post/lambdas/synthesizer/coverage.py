from __future__ import annotations

import logging
from typing import TypedDict

from synthesizer.input_graph import Site, haversine_miles
from synthesizer.model import Synthesis, SynthesisInputs, SynthesisParams
from synthesizer.assemble import build_synthesis_for_backbone, evaluate_backbone
from synthesizer.ceiling import BackupPathLimit, PathProofInputs, independent_path_ceiling
from synthesizer.search_plan import _SearchPlan

logger = logging.getLogger(__name__)


class CoverageReport(TypedDict):
    target_miles: float
    worst_haul_miles: float
    sites_above_target: int
    met: bool


def demand_hauls(
    backbone_ids: tuple[str, ...],
    access_sites: list[Site],
    pop_by_id: dict[str, Site],
) -> list[float]:
    nodes = [pop_by_id[backbone_id] for backbone_id in backbone_ids]
    return [
        min(haversine_miles(access, node) for node in nodes) for access in access_sites
    ]


def coverage_haul_profile(
    backbone_ids: tuple[str, ...],
    access_sites: list[Site],
    pop_by_id: dict[str, Site],
) -> tuple[float, ...]:
    covered = [v for v in access_sites if not v.exempt_from_distance_constraint]
    return tuple(sorted(demand_hauls(backbone_ids, covered, pop_by_id), reverse=True))


def coverage_worst_haul(profile: tuple[float, ...]) -> float:
    return max(profile, default=0.0)


def coverage_report(
    backbone_ids: tuple[str, ...],
    access_sites: list[Site],
    pop_by_id: dict[str, Site],
    target_miles: float,
) -> CoverageReport:
    profile = coverage_haul_profile(backbone_ids, access_sites, pop_by_id)
    worst = coverage_worst_haul(profile)
    return {
        "target_miles": target_miles,
        "worst_haul_miles": round(worst, 1),
        "sites_above_target": sum(1 for haul in profile if haul > target_miles),
        "met": worst <= target_miles,
    }


def coverage_candidate_hauls(
    backbone_ids: tuple[str, ...],
    free: list[str],
    inputs: SynthesisInputs,
    plan: _SearchPlan,
    pop_by_id: dict[str, Site],
) -> list[tuple[tuple[float, ...], str]]:
    hauls: list[tuple[tuple[float, ...], str]] = []
    for candidate_id in free:
        candidate_set = tuple(sorted((*backbone_ids, candidate_id)))
        if evaluate_backbone(candidate_set, inputs, plan) is None:
            continue
        profile = coverage_haul_profile(candidate_set, inputs.access_sites, pop_by_id)
        hauls.append((profile, candidate_id))
    return hauls


def candidate_mesh_ceiling(
    candidate_id: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: BackupPathLimit | None = None,
) -> int:
    return independent_path_ceiling(
        candidate_id,
        PathProofInputs(tuple(sorted((*backbone_ids, candidate_id))), adjacency, limit),
    )


def best_coverage_candidate(
    improving: list[tuple[tuple[float, ...], str]],
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    target_miles: float,
    limit: BackupPathLimit | None = None,
) -> str:
    satisfying = [
        pair for pair in improving if coverage_worst_haul(pair[0]) <= target_miles
    ]
    if not satisfying:
        return min(improving)[1]
    return min(
        satisfying,
        key=lambda pair: (
            -candidate_mesh_ceiling(pair[1], backbone_ids, adjacency, limit),
            pair[0],
            pair[1],
        ),
    )[1]


def grow_backbone_for_coverage(
    base_ids: tuple[str, ...],
    inputs: SynthesisInputs,
    plan: _SearchPlan,
    params: SynthesisParams,
    pop_by_id: dict[str, Site],
) -> Synthesis:
    target_miles = params.tuning.backbone_coverage_target_miles
    backbone_ids = base_ids
    free = [pop_id for pop_id in plan.backbone_candidates if pop_id not in backbone_ids]
    logger.info(
        "Growing backbone for coverage: %d candidates, %.0f mi target", len(free), target_miles
    )
    while free:
        if params.max_backbone_count is not None and len(backbone_ids) >= params.max_backbone_count:
            logger.info("Coverage growth stopped at the %d-node cap", len(backbone_ids))
            break
        profile = coverage_haul_profile(backbone_ids, inputs.access_sites, pop_by_id)
        worst = coverage_worst_haul(profile)
        if worst <= target_miles:
            logger.info("Coverage met at %d nodes (worst haul %.0f mi)", len(backbone_ids), worst)
            break
        logger.info(
            "Coverage round at %d nodes: worst haul %.0f mi > %.0f target; scoring %d candidates",
            len(backbone_ids), worst, target_miles, len(free),
        )
        candidates = coverage_candidate_hauls(backbone_ids, free, inputs, plan, pop_by_id)
        improving = [pair for pair in candidates if pair[0] < profile]
        if not improving:
            logger.info("No candidate improves coverage; holding at %d nodes", len(backbone_ids))
            break
        best_id = best_coverage_candidate(
            improving,
            backbone_ids,
            inputs.adjacency,
            target_miles,
            BackupPathLimit(
                params.tuning.backbone_max_backup_path_multiple, inputs.all_distances
            ),
        )
        backbone_ids = tuple(sorted((*backbone_ids, best_id)))
        free.remove(best_id)
        logger.info("Added node %s for coverage; now %d nodes", best_id, len(backbone_ids))
    grown = build_synthesis_for_backbone(backbone_ids, inputs, plan)
    assert grown is not None
    return grown
