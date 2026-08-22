"""Assemble a complete two-tier synthesis for one fixed set of backbone PoPs.

Everything here answers the same question: given these backbone nodes, what synthesis do they
make, and do they make one at all. Nothing here chooses the backbone nodes -- the search
that does that (:mod:`synthesizer.synthesize`) and the coverage growth that adds to them
(:mod:`synthesizer.coverage`) both stand above this module and both call into it.

Keeping it separate is what lets those two be separate. The growth step has to build a
synthesis to judge a candidate, and the search has to grow the backbone once it has a base, so
if the builder lived with either one the other would have to import it and the two would
point at each other.
"""

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
    """A synthesis before its mileage is added up: what it homes, what it paths, its floor.

    ``backbone_lower_bound_miles`` is the fewest fiber miles any backbone meeting this
    tenant's requirements could have run (see :mod:`synthesizer.survivable`). It is carried
    here so it reaches :class:`synthesizer.model.SynthesisMetrics` and is published with the
    synthesis; a draft built without a fiber choice behind it carries no floor and reads zero.
    """

    access_paths: list[AccessPath]
    path_uses: list[SynthesisPath]
    backbone_lower_bound_miles: float = 0.0


def finalize_synthesis(
    backbone_ids: tuple[str, ...],
    draft: _SynthesisDraft,
    fiber_segments: dict[tuple[str, str], FiberSegment],
) -> Synthesis:
    """Compute link sets, mileage estimate, and score for a synthesis draft."""
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
    """Id of the Carrier PoP nearest to an access site."""
    return min(carrier_pops, key=lambda pop: haversine_miles(access, pop)).id


def assign_access(
    backbone_ids: tuple[str, ...],
    inputs: SynthesisInputs,
    plan: _SearchPlan,
) -> list[AccessPath] | None:
    """Home every demand site to its nearest backbone nodes in a single pass.

    Each demand site (a unified tenant site or provider region) homes to its
    ``plan.tuning.access_backbone_links`` nearest selected backbone nodes, ranked by
    great-circle distance, with any operator-forced access-backbone link leading its
    homes regardless of distance. The same code path serves tenant and provider demand --
    they differ only by source kind at output time. Returns the access links, or None
    when the backbone is smaller than the configured number of homes (no site could
    reach that many distinct nodes).
    """
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
    """True if the backbone nodes can be wired into a city-survivable physical-fiber mesh.

    They can iff they all share one common biconnected block of the carrier graph --
    otherwise some single city separates two of them and no routing survives its loss.
    Being city-survivable implies segment-survivable, so this subsumes the old
    link-survivability gate.
    """
    common: frozenset[int] | None = None
    for node in backbone_ids:
        blocks = inputs.carrier_blocks.get(node, frozenset())
        common = blocks if common is None else common & blocks
    return common is not None and bool(common)


def forced_backbone_resilience_error(
    required: frozenset[str], inputs: SynthesisInputs, min_count: int
) -> str | None:
    """Why the operator's forced backbone nodes can never form a resilient synthesis, or None.

    A forced node behind a single carrier city (sharing no block with the other forced
    nodes, or sitting in no cyclic block at all) makes every candidate set fail the
    physical gate, so the search would end with an opaque "no feasible synthesis". Caught up
    front, this names the offending nodes so the operator can fix ``etc/*.yml`` -- the
    reject rule wins over the force.
    """
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
    """Score a backbone set's feasibility and demand homing without routing paths.

    Returns None when the backbone nodes cannot be wired into a city-survivable physical-
    fiber mesh (a single city loss would strand one -- which also rules out a node that
    cannot reach its peers, since biconnectivity implies they are all mutually reachable),
    or the backbone is smaller than the configured number of homes per demand site (so
    ``assign_access`` cannot give each demand site that many distinct backbone nodes).
    The synthesis's paths are deferred to the winning set, since they do not affect the ranking.
    """
    if not backbone_physically_biconnectable(backbone_ids, inputs):
        return None
    return assign_access(backbone_ids, inputs, plan)


def synthesis_paths(
    backbone_ids: tuple[str, ...],
    inputs: SynthesisInputs,
    plan: _SearchPlan,
    fiber_segments: dict[tuple[str, str], FiberSegment],
) -> BackboneMesh:
    """Draw the backbone-to-backbone paths for a synthesis, and the floor they are judged against.

    The operator's instructions are gathered here and handed over whole: the pairs they
    pinned, the pairs they struck out, how many ways out each site is owed, how far a
    path may run against the direct distance between its ends, and how many seats their
    config allows. What comes back is the paths and the fewest miles any synthesis meeting the
    same requirements could have run (see :class:`synthesizer.backbone.BackboneMesh`).
    """
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
    """Assemble a full two-tier synthesis for one fixed set of backbone PoPs.

    Returns None if a backbone node cannot reach enough peers to wire its mesh links, or
    the backbone is too small to give each demand site its configured number of homes.
    """
    access_paths = evaluate_backbone(backbone_ids, inputs, plan)
    if access_paths is None:
        return None
    mesh = synthesis_paths(backbone_ids, inputs, plan, inputs.fiber_segments)
    draft = _SynthesisDraft(access_paths, mesh.paths, mesh.lower_bound_miles)
    return finalize_synthesis(backbone_ids, draft, inputs.fiber_segments)
