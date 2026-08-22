from __future__ import annotations

from dataclasses import dataclass

from synthesizer.input_graph import FiberSegment, Site, haversine_miles
from synthesizer.model import (
    AccessPath,
    Synthesis,
    SynthesisInputs,
    SynthesisMetrics,
    SynthesisPath,
)
from synthesizer.forced import (
    apply_forced_access_homes,
    forced_backbone_pairs,
    removed_backbone_pairs,
)
from synthesizer.graphs import path_link_keys
from synthesizer.backbone import BackboneConstraints, BackboneMesh, backbone_mesh
from synthesizer.ceiling import BackupPathLimit
from synthesizer.search_plan import _SearchPlan


@dataclass
class _SynthesisDraft:
    access_paths: list[AccessPath]
    path_uses: list[SynthesisPath]
    backbone_lower_bound_miles: float = 0.0


def finalize_synthesis(
    backbone_ids: tuple[str, ...],
    draft: _SynthesisDraft,
    fiber_segments: dict[tuple[str, str], FiberSegment],
) -> Synthesis:
    fiber_segment_keys: set[tuple[str, str]] = set()
    for path_use in draft.path_uses:
        fiber_segment_keys.update(path_link_keys(path_use.path))

    access_miles = sum(link.distance_miles for link in draft.access_paths)
    physical_miles = sum(
        fiber_segments[key].distance_miles for key in fiber_segment_keys
    )
    score = access_miles + physical_miles
    carrier_on_paths = {site_id for use in draft.path_uses for site_id in use.path}
    transit_ids = tuple(sorted(carrier_on_paths - set(backbone_ids)))
    return Synthesis(
        backbone_ids=backbone_ids,
        transit_ids=transit_ids,
        access_paths=draft.access_paths,
        fiber_segment_keys=fiber_segment_keys,
        path_uses=draft.path_uses,
        metrics=SynthesisMetrics(
            score, access_miles, physical_miles, draft.backbone_lower_bound_miles
        ),
    )


def nearest_pop_id(access: Site, carrier_pops: list[Site]) -> str:
    return min(carrier_pops, key=lambda pop: haversine_miles(access, pop)).id


def assign_access(
    backbone_ids: tuple[str, ...],
    inputs: SynthesisInputs,
    plan: _SearchPlan,
) -> list[AccessPath] | None:
    links = plan.tuning.access_backbone_links
    backbone_set = set(backbone_ids)
    if len(backbone_set) < links:
        return None
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    access_paths: list[AccessPath] = []
    for access in inputs.access_sites:
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
        access_paths.extend(
            AccessPath(
                access.id, backbone_id,
                haversine_miles(access, pop_by_id[backbone_id]),
            )
            for backbone_id in completed
        )
    return access_paths


def backbone_physically_biconnectable(
    backbone_ids: tuple[str, ...], inputs: SynthesisInputs
) -> bool:
    common: frozenset[int] | None = None
    for node in backbone_ids:
        blocks = inputs.carrier_blocks.get(node, frozenset())
        common = blocks if common is None else common & blocks
    return common is not None and bool(common)


def forced_backbone_resilience_error(
    required: frozenset[str], inputs: SynthesisInputs, min_count: int
) -> str | None:
    if not required:
        return None
    blocks_by_id = inputs.carrier_blocks
    pop_by_id = {pop.id: pop for pop in inputs.carrier_pops}
    names = ", ".join(sorted(pop_by_id[node].name for node in required))
    common = blocks_by_id.get(next(iter(required)), frozenset())
    for node in required:
        common &= blocks_by_id.get(node, frozenset())
    if not common:
        return (
            "Forced backbone nodes share no common biconnected block of the carrier fiber "
            f"graph, so no synthesis can survive a single city loss: {names}"
        )
    best = max(
        sum(
            1
            for node in inputs.eligible_backbone_ids
            if block in blocks_by_id.get(node, frozenset())
        )
        for block in common
    )
    if best < min_count:
        return (
            "A forced backbone node sits in a carrier fiber pocket too small for a "
            f"{min_count}-node biconnected backbone: {names}"
        )
    return None


def evaluate_backbone(
    backbone_ids: tuple[str, ...],
    inputs: SynthesisInputs,
    plan: _SearchPlan,
) -> list[AccessPath] | None:
    if not backbone_physically_biconnectable(backbone_ids, inputs):
        return None
    return assign_access(backbone_ids, inputs, plan)


def synthesis_paths(
    backbone_ids: tuple[str, ...],
    inputs: SynthesisInputs,
    plan: _SearchPlan,
    fiber_segments: dict[tuple[str, str], FiberSegment],
) -> BackboneMesh:
    backbone_set = set(backbone_ids)
    constraints = BackboneConstraints(
        removed_backbone_pairs(backbone_set, plan.forced_links),
        number_of_diverse_paths=plan.tuning.backbone_number_of_diverse_paths,
        forced_pairs=forced_backbone_pairs(backbone_set, plan.forced_links),
        limit=BackupPathLimit(
            plan.tuning.backbone_max_backup_path_multiple, inputs.all_distances
        ),
        seat_cap=plan.seat_cap,
    )
    return backbone_mesh(backbone_ids, inputs.all_distances, fiber_segments, constraints)


def build_synthesis_for_backbone(
    backbone_ids: tuple[str, ...],
    inputs: SynthesisInputs,
    plan: _SearchPlan,
) -> Synthesis | None:
    access_paths = evaluate_backbone(backbone_ids, inputs, plan)
    if access_paths is None:
        return None
    mesh = synthesis_paths(backbone_ids, inputs, plan, inputs.fiber_segments)
    draft = _SynthesisDraft(access_paths, mesh.paths, mesh.lower_bound_miles)
    return finalize_synthesis(backbone_ids, draft, inputs.fiber_segments)
