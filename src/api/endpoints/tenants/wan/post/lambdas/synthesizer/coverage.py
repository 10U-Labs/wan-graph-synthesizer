"""Grow the backbone past its strength-chosen base until demand is close enough.

The search picks the strongest backbone it can at the floor. That backbone answers a
question about fiber, not about where anybody actually is, so some demand may still sit
farther from it than the operator allows. This module adds nodes until that is no longer
true, and decides which node to add.

Two questions decide a round and they are asked in that order: coverage says which
candidates are admissible, and fiber says which of those is worth seating. Both are written
up where they are answered, in :func:`grow_backbone_for_coverage` and
:func:`best_coverage_candidate`. What the delivered design did about the target is
reported by :func:`coverage_report`, since growth can stop without having met it.
"""

from __future__ import annotations

import logging
from typing import TypedDict

from synthesizer.input_graph import Vertex, haversine_miles
from synthesizer.model import Design, DesignInputs, DesignParams
from synthesizer.assemble import build_design_for_backbone, evaluate_backbone
from synthesizer.ceiling import StretchLimit, independent_route_ceiling
from synthesizer.search_plan import _SearchPlan

logger = logging.getLogger(__name__)


class CoverageReport(TypedDict):
    """What a delivered design does about the coverage target it was built to."""

    target_miles: float
    worst_haul_miles: float
    sites_above_target: int
    met: bool


def demand_hauls(
    backbone_ids: tuple[str, ...],
    access_vertices: list[Vertex],
    pop_by_id: dict[str, Vertex],
) -> list[float]:
    """Each demand vertex's straight-line miles to its nearest backbone node.

    The coverage signal the search drives down by adding backbone nodes: the hauls an
    operator sees on the map, and the quantity the coverage target is stated in.
    """
    nodes = [pop_by_id[backbone_id] for backbone_id in backbone_ids]
    return [
        min(haversine_miles(access, node) for node in nodes) for access in access_vertices
    ]


def coverage_haul_profile(
    backbone_ids: tuple[str, ...],
    access_vertices: list[Vertex],
    pop_by_id: dict[str, Vertex],
) -> tuple[float, ...]:
    """Every non-exempt site's haul to its nearest backbone node, worst first.

    Sites the operator marked exempt from the distance constraint (OCONUS) are dropped:
    each may sit farther than any backbone node can reach, so counting one would hold growth
    open to the node cap. They still drive hub scoring and home to their nearest node
    elsewhere; only coverage ignores them. An all-exempt design reads as empty.

    The whole list rather than its worst entry, because one number cannot say whether a hub
    helped anybody. Two sites that need separate hubs and whose hauls sit within a mile of
    each other take turns at the top of the list, so a hub rescuing either one moves the
    worst number by the gap between them and by nothing else -- a hub bringing a site four
    hundred miles closer reads as having achieved four tenths of a mile, and a second site
    at exactly equal haul makes it read as having achieved nothing at all. Compared position
    by position, the same hub is plainly the better design: the two lists first differ where
    the rescued site used to be.
    """
    covered = [v for v in access_vertices if not v.exempt_from_distance_constraint]
    return tuple(sorted(demand_hauls(backbone_ids, covered, pop_by_id), reverse=True))


def coverage_worst_haul(profile: tuple[float, ...]) -> float:
    """The worst haul in a coverage profile -- the stop signal. An empty profile reads 0."""
    return max(profile, default=0.0)


def coverage_report(
    backbone_ids: tuple[str, ...],
    access_vertices: list[Vertex],
    pop_by_id: dict[str, Vertex],
    target_miles: float,
) -> CoverageReport:
    """Measure a finished design against the coverage target it was built to.

    Growth ends on one of four things -- the target met, the seat cap reached, the
    candidates exhausted, or no candidate improving on the design in hand -- and only the
    first is success. Rather than carry which one fired, this measures the design that came
    out: the worst haul over the sites the target applies to, and how many of them sit
    outside it. A design that stopped short then says so somewhere a caller can read it,
    instead of being published under the same word as one that met the target.
    """
    profile = coverage_haul_profile(backbone_ids, access_vertices, pop_by_id)
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
    inputs: DesignInputs,
    plan: _SearchPlan,
    pop_by_id: dict[str, Vertex],
) -> list[tuple[tuple[float, ...], str]]:
    """Each free candidate's non-exempt haul profile once it joins the backbone.

    This is the same quantity :func:`coverage_haul_profile` measures and the same one the
    growth loop stops on, which is the whole point of it. A round opens because some site
    the target applies to is too far from every backbone node, so the candidate worth
    seating is the one that leaves that site closest -- not the one that shaves the most
    miles off sites already inside the target, and not one chosen with the help of sites
    the target was deliberately lifted from.

    Infeasible additions (a candidate whose promotion strands demand) are dropped, so
    every returned pair is a buildable grown set beside the coverage it would deliver.
    """
    hauls: list[tuple[tuple[float, ...], str]] = []
    for candidate_id in free:
        candidate_set = tuple(sorted((*backbone_ids, candidate_id)))
        if evaluate_backbone(candidate_set, inputs, plan) is None:
            continue
        profile = coverage_haul_profile(candidate_set, inputs.access_vertices, pop_by_id)
        hauls.append((profile, candidate_id))
    return hauls


def candidate_mesh_ceiling(
    candidate_id: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: StretchLimit | None = None,
) -> int:
    """How many independently failing links ``candidate_id`` could hold once it joins.

    The number of routes from it to the rest of the grown backbone that no single city's
    loss takes two of (see :func:`synthesizer.ceiling.independent_route_ceiling`).

    This is not the number of fiber spans leaving the city, and the difference is the whole
    reason to measure it rather than count them. A city with three spans whose branches
    funnel through one upstream city can hold two links that fail independently, not three,
    so a raw span count would say it can carry a backbone node when its fiber cannot.

    ``limit`` bounds how far the routes counted may run (see
    :func:`synthesizer.ceiling.independent_routes`). A hub credited with a route it could
    only take by crossing an ocean is chosen for protection the operator will not buy, so
    the bound belongs to the ranking as much as to the routing.
    """
    return independent_route_ceiling(
        candidate_id, tuple(sorted((*backbone_ids, candidate_id))), adjacency, limit
    )


def best_coverage_candidate(
    improving: list[tuple[tuple[float, ...], str]],
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    target_miles: float,
    limit: StretchLimit | None = None,
) -> str:
    """Which improving candidate to seat: the best connected of those that satisfy coverage.

    The coverage target is a constraint on how far the backbone may leave demand, not a cost
    to be minimised. Once a candidate brings the worst haul inside the target it has fully
    answered the question the round asked, and seating a nearer one instead buys nothing the
    operator asked for. So coverage narrows the field and does not order it.

    Among the candidates left, the one whose fiber can carry the most independently failing
    links wins (see :func:`candidate_mesh_ceiling`). A hub is chosen for what its fiber can
    do rather than for where it sits, which is the position the base backbone search already
    takes when it ranks sets by strength, and the reason the spec forbids mileage as a design
    cost. A city that satisfies coverage and then cannot hold the links a backbone node is
    required to hold has not solved the problem, it has moved it.

    Distance decides only what fiber cannot. Where no candidate reaches the target none has
    answered the round, so the one leaving the best haul profile is seated and the next
    round asks again -- a preference for well-connected fiber must never hold a gap open.
    Ties are settled by profile and then by id, so the choice is deterministic.
    """
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
    base: Design,
    inputs: DesignInputs,
    plan: _SearchPlan,
    params: DesignParams,
    pop_by_id: dict[str, Vertex],
) -> Design:
    """Add backbone nodes beyond the strength-chosen base until demand is close enough.

    While some demand vertex the target applies to is farther than
    ``backbone_coverage_target_miles`` from every selected backbone node, seat one more
    candidate and rebuild the design around it. Extra nodes are thus coverage-driven:
    strength still chooses the base backbone, and the operator's coverage target is a
    constraint on how far the backbone may leave demand, not a mileage cost minimized over
    candidate sets. Growth stops once every non-exempt demand vertex is within target, the
    backbone reaches ``max_backbone_count``, no remaining candidate leaves any site nearer
    than the design already does, or the candidates are exhausted. Only the first of those
    is success, which is why :func:`coverage_report` measures what came out.

    Two questions decide a round and they are asked in that order. Which candidates are
    admissible is a coverage question, and one measure has to answer it in all three places
    -- the stop test, the scoring and the progress filter -- or the loop argues with itself.
    That measure is the haul profile over the sites the target applies to: every one of
    their hauls, worst first, compared position by position. Were candidates scored by the
    summed haul over every site instead, a round could be won by a node that shortens many
    sites already inside the target while leaving the far one where it was, and the exempt
    sites, exempt precisely because they are far from everything, would contribute the
    largest terms to that sum and so have the most say in a choice they were lifted out of.
    The round would spend a node and come round again with the gap still open.

    Judging progress on the worst haul alone was the same error read the other way. It
    asks whether the worst number on the board moved rather than whether a hub helped a
    site, and the two part company the moment a second site is queued just behind the
    first: seating the hub that rescues the leader promotes the runner-up, the board barely
    moves, and the round reports that nothing improved while a site went from five hundred
    miles of haul to fifty. Two sites at exactly equal haul deadlock such a test at any
    tolerance, which is why there is no tolerance to tune here and the profiles are simply
    compared. Growth is bounded regardless: each round spends a candidate, and the stop
    test above ends it as soon as the target is met.

    Which of the admissible candidates to seat is not a coverage question at all, and
    answering it with distance was the second half of the same mistake. Among candidates
    that satisfy the target, the best-connected one is seated (see
    :func:`best_coverage_candidate`), because a hub that meets the distance requirement and
    then cannot hold the links a backbone node owes has not solved anything.
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
        # One quantity runs the whole round: the haul profile over the sites the target
        # applies to. It decides whether to stop, which candidate wins, and whether any
        # candidate is worth seating -- so the round cannot be won by a node that does
        # nothing about the gap that opened it, nor abandoned by a node that plainly helps.
        profile = coverage_haul_profile(backbone_ids, inputs.access_vertices, pop_by_id)
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
            StretchLimit(params.tuning.backbone_max_path_stretch, inputs.all_distances),
        )
        backbone_ids = tuple(sorted((*backbone_ids, best_id)))
        grown = build_design_for_backbone(backbone_ids, inputs, plan)
        # The winning candidate already passed evaluate_backbone above, so its design builds.
        assert grown is not None
        design = grown
        free.remove(best_id)
        logger.info("Added node %s for coverage; now %d nodes", best_id, len(backbone_ids))
    return design
