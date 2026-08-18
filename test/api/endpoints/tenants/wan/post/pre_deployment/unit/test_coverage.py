"""Unit tests for growing the backbone until demand is close enough."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

import fixtures
from fixtures import design_inputs_from_edges, search_plan
from synthesizer.assemble import build_design_for_backbone
from synthesizer.input_graph import PhysicalEdge, Vertex, haversine_miles
from synthesizer.graphs import build_adjacency
from synthesizer.model import Design, DesignParams, Tuning
from synthesizer.coverage import (
    CoverageReport,
    best_coverage_candidate,
    candidate_mesh_ceiling,
    coverage_candidate_hauls,
    coverage_haul_profile,
    coverage_report,
    coverage_worst_haul,
    demand_hauls,
    grow_backbone_for_coverage,
)

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from
access = fixtures.access_vertex


def _wired_to_base(names: tuple[str, ...]) -> dict[tuple[str, str], PhysicalEdge]:
    """Fiber joining the base pair b1/b2 and hanging every named place off both of them.

    Every grown set is then a biconnected triangle that builds and every site homes, so
    geography alone decides what a round does.
    """
    return physical(
        {
            ("b1", "b2"): 1.0,
            **{(name, base): 1.0 for name in names for base in ("b1", "b2")},
        }
    )


def test_demand_hauls_report_each_site_by_its_nearest_node() -> None:
    """The haul metric gives each demand vertex its miles to the nearest backbone node."""
    pops = {
        "node_w": pop("node_w", 40.0, -100.0),
        "node_e": pop("node_e", 40.0, -80.0),
        "near": access("near", 40.0, -99.0),
        "far": access("far", 40.0, -90.0),
    }
    expected = [
        haversine_miles(pops["near"], pops["node_w"]),
        haversine_miles(pops["far"], pops["node_w"]),
    ]
    result = demand_hauls(("node_w", "node_e"), [pops["near"], pops["far"]], pops)
    assert result == pytest.approx(expected)


def test_the_coverage_profile_ignores_exempt_sites() -> None:
    """The coverage measure skips sites marked exempt from the distance constraint."""
    pops = {"node": pop("node", 40.0, -100.0)}
    near = access("near", 40.0, -99.0)
    far = replace(access("far", 10.0, -160.0), exempt_from_distance_constraint=True)
    assert coverage_haul_profile(("node",), [near, far], pops) == pytest.approx(
        (haversine_miles(near, pops["node"]),)
    )


def test_an_all_exempt_design_has_no_worst_haul() -> None:
    """Every site lifted out of the target leaves an empty profile, which reads as zero."""
    assert coverage_worst_haul(()) == 0.0


def test_coverage_candidate_hauls_drops_an_infeasible_addition() -> None:
    """A candidate that makes the grown backbone infeasible is dropped from the scoring.

    Demand ``s`` homes to c1/c2, but the candidate ``z`` sits in its own component and
    cannot reach a mesh peer, so promoting it yields an unbuildable backbone -- the
    coverage scorer offers it nothing.
    """
    edges = physical(
        {
            ("c1", "c2"): 1.0, ("s", "c1"): 1.0, ("s", "c2"): 1.0, ("z", "y"): 1.0,
        }
    )
    inputs = design_inputs_from_edges(
        ["c1", "c2", "z", "y"], edges, {"c1", "c2", "z"}, [access("s", 0.0, 0.05)]
    )
    hauls = coverage_candidate_hauls(("c1", "c2"), ["z"], inputs, search_plan([]), {
        "c1": pop("c1", 0.0, 0.0), "c2": pop("c2", 0.0, 0.1), "z": pop("z", 0.0, 0.2)
    })
    assert not hauls


# The geometry where ranking by the worst haul and ranking by the summed one disagree.
# Three demand sites sit a degree west of the base pair and a fourth sits two degrees east,
# outside any target the western three are inside. Seating "east" closes that far site and
# leaves the worst haul at the western distance; seating "west" zeroes the three and leaves
# the far site exactly where it was. Three short hauls outweigh one long one, so a score
# that sums every site prefers "west" -- and the site that opened the round stays out of
# reach, which is the whole of what the wrong measure costs.
_RANKING_EDGES = _wired_to_base(
    ("east", "west", "oversea", "far", "near1", "near2", "near3", "oconus")
)
_RANKING_COORDS = {
    "b1": (0.0, 0.0), "b2": (0.05, 0.0),
    "east": (0.0, 2.0), "west": (0.0, -1.0), "oversea": (0.0, -40.0),
}
_RANKING_IDS = ["b1", "b2", "east", "west", "oversea"]
_RANKING_SITES = [
    access("far", 0.0, 2.0),
    access("near1", 0.0, -1.0), access("near2", 0.05, -1.0), access("near3", -0.05, -1.0),
]
# Forty degrees out and exempt from the target: it dominates every distance in the design
# and none of them are its business, so it must have no say in which candidate wins.
_OCONUS_SITE = replace(access("oconus", 0.0, -40.0), exempt_from_distance_constraint=True)


def _ranking_hauls(
    candidates: list[str], sites: list[Vertex]
) -> list[tuple[tuple[float, ...], str]]:
    """Score each candidate over the ranking geometry against the given demand."""
    inputs = design_inputs_from_edges(
        _RANKING_IDS, _RANKING_EDGES, set(_RANKING_IDS), sites, _RANKING_COORDS
    )
    return coverage_candidate_hauls(
        ("b1", "b2"), candidates, inputs, search_plan(_RANKING_IDS),
        {carrier.id: carrier for carrier in inputs.carrier_pops},
    )


def test_the_candidate_that_closes_the_gap_outranks_the_one_that_shortens_the_rest() -> None:
    """The round opened on the far site, so the node that reaches it is the one that wins."""
    assert min(_ranking_hauls(["east", "west"], _RANKING_SITES))[1] == "east"


def test_a_site_exempt_from_the_target_cannot_sway_which_candidate_wins() -> None:
    """A candidate that only helps the exempt site helps nothing the round is about."""
    assert min(_ranking_hauls(["east", "oversea"], [*_RANKING_SITES, _OCONUS_SITE]))[1] == "east"


# Fiber where segment counts and independent paths disagree. Three base nodes sit in a triangle.
# "rich" and "rich_far" reach all three directly, so each holds three links that fail
# independently. "poor" and "poor_far" reach two directly and spend their third segment on a
# stub that rejoins the backbone at b1, so that third path can only re-cross a city they
# already depend on and each holds two. Three segments apiece either way, which is the number
# a raw segment count would rank them by and the reason it is the wrong number to rank them by.
_FIBER_EDGES = physical({
    ("b1", "b2"): 1.0, ("b2", "b3"): 1.0, ("b1", "b3"): 1.0,
    ("poor", "x"): 1.0, ("x", "b1"): 1.0, ("poor_far", "x2"): 1.0, ("x2", "b1"): 1.0,
    **{(name, base): 1.0 for name in ("rich", "rich_far") for base in ("b1", "b2", "b3")},
    **{(name, base): 1.0 for name in ("poor", "poor_far") for base in ("b1", "b2")},
})
_FIBER_ADJACENCY = build_adjacency(_FIBER_EDGES)
_FIBER_BACKBONE = ("b1", "b2", "b3")
# Both bring the worst haul inside the fifty-mile target and the worse-connected one is
# nearer, so distance and fiber name different winners. In the second pair neither reaches
# the target, and again the worse-connected one is nearer. One site each, so the profile a
# real round would compare is a single haul.
_BOTH_COVER: list[tuple[tuple[float, ...], str]] = [((0.0,), "poor"), ((6.9,), "rich")]
_NEITHER_COVERS: list[tuple[tuple[float, ...], str]] = [
    ((103.6,), "poor_far"), ((138.2,), "rich_far"),
]


def _seated(improving: list[tuple[tuple[float, ...], str]]) -> str:
    """Which of these candidates the growth step seats over the fiber above, at 50 miles."""
    return best_coverage_candidate(improving, _FIBER_BACKBONE, _FIBER_ADJACENCY, 50.0)


def test_the_better_connected_of_two_covering_candidates_is_seated() -> None:
    """Coverage is answered by both, so the one whose fiber carries more links wins."""
    assert _seated(_BOTH_COVER) == "rich"


def test_a_candidates_segments_are_not_counted_as_independent_paths() -> None:
    """Three segments leave poor, and two independent paths out are all its own fiber allows."""
    assert candidate_mesh_ceiling("poor", _FIBER_BACKBONE, _FIBER_ADJACENCY) == 2


def test_the_nearest_candidate_is_seated_when_none_satisfies_the_target() -> None:
    """No candidate answers the round, so the gap is closed as far as it can be instead."""
    assert _seated(_NEITHER_COVERS) == "poor_far"


# The geometry the growth loop used to stop dead on. Two sites sit seven and a half degrees
# either side of the base pair, more than five hundred miles out and two thirds of a mile
# apart in haul; no one candidate serves both, since they are fifteen degrees apart. "cape"
# rescues the eastern site and "plains" the western one, and each leaves the other where it
# was, so seating either moves the worst number on the board by the gap between the two
# sites and by nothing else. "twin" sits on a base node and rescues nobody.
_GROWTH_COORDS = {
    "b1": (0.0, 0.0), "b2": (0.05, 0.0),
    "cape": (0.0, 7.4), "plains": (0.0, -7.39), "twin": (0.0, 0.0),
}
_GROWTH_IDS = ["b1", "b2", "cape", "plains", "twin"]
_GROWTH_EDGES = _wired_to_base(("cape", "plains", "twin", "east_site", "west_site"))
_GROWTH_SITES = [access("east_site", 0.0, 7.5), access("west_site", 0.0, -7.49)]


def _grown(candidates: list[str], target_miles: int) -> tuple[str, ...]:
    """The backbone growth settles on over that geometry, offered these candidates."""
    inputs = design_inputs_from_edges(
        _GROWTH_IDS, _GROWTH_EDGES, set(_GROWTH_IDS), _GROWTH_SITES, _GROWTH_COORDS
    )
    plan = search_plan(candidates)
    base = cast(Design, build_design_for_backbone(("b1", "b2"), inputs, plan))
    params = DesignParams(
        min_backbone_count=2, tuning=Tuning(backbone_coverage_target_miles=target_miles)
    )
    grown = grow_backbone_for_coverage(
        base, inputs, plan, params,
        {carrier.id: carrier for carrier in inputs.carrier_pops},
    )
    return tuple(sorted(grown.backbone_ids))


def test_growth_continues_when_the_two_worst_sites_are_a_hub_apart_each() -> None:
    """Two sites within a mile of each other in haul no longer halt growth between them.

    Seating either hub rescues one site and hands the top of the list to the other, so the
    worst haul moves by two thirds of a mile and a round judged on that number reads a
    five-hundred-mile rescue as having achieved nothing worth a seat. Both hubs are seated
    here and both sites end up inside the target.
    """
    assert _grown(_GROWTH_IDS, 100) == ("b1", "b2", "cape", "plains")


def test_growth_stops_when_no_candidate_leaves_any_site_nearer() -> None:
    """A round where the only candidate changes no site's haul still ends growth.

    ``twin`` sits on a node already seated, so it rescues nobody. The loop has to read that
    as finished rather than spend the seat and come round again, which is the failure the
    fix above must not trade the premature stop for.
    """
    assert _grown(["b1", "b2", "twin"], 100) == ("b1", "b2")


# One hub with a site well inside any sane target and another well outside it, so the same
# design reads as having met a loose target and missed a tight one.
_REPORT_POPS = {"hub": pop("hub", 40.0, -100.0)}
_REPORT_SITES = [access("near", 40.0, -100.5), access("far", 40.0, -95.0)]


def _report(target_miles: float) -> CoverageReport:
    """What that design reports about itself against the given target."""
    return coverage_report(("hub",), _REPORT_SITES, _REPORT_POPS, target_miles)


def test_a_design_that_stopped_short_reports_the_target_unmet() -> None:
    """A design leaving a site outside the target says so rather than reading as finished."""
    assert _report(100.0)["met"] is False


def test_a_design_inside_the_target_reports_it_met() -> None:
    """Every site within the target is what success looks like, and the report says it."""
    assert _report(400.0)["met"] is True


def test_the_report_counts_the_sites_left_outside_the_target() -> None:
    """How many sites the design gave up on, which "not met" alone does not say."""
    assert _report(100.0)["sites_above_target"] == 1


def test_the_report_carries_the_worst_haul_it_measured() -> None:
    """The furthest a site was left from the backbone, the number the target is stated in."""
    assert _report(100.0)["worst_haul_miles"] == round(
        haversine_miles(_REPORT_SITES[1], _REPORT_POPS["hub"]), 1
    )


def test_the_report_echoes_the_target_it_was_measured_against() -> None:
    """The target travels with the measurement, so a reader needs no second document."""
    assert _report(100.0)["target_miles"] == 100.0
