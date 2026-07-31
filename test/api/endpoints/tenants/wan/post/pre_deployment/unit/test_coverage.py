"""Unit tests for growing the backbone until demand is close enough."""

from __future__ import annotations

from dataclasses import replace

import pytest

import fixtures
from synthesizer.input_graph import Vertex, haversine_miles
from synthesizer.graphs import build_adjacency
from synthesizer.coverage import (
    best_coverage_candidate,
    candidate_mesh_ceiling,
    coverage_candidate_hauls,
    coverage_worst_haul,
    demand_haul_miles,
)

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from
access = fixtures.access_vertex
_inputs_from_edges = fixtures.design_inputs_from_edges
_plan = fixtures.search_plan

def test_demand_haul_miles_reports_the_worst_distance_to_a_nearest_node() -> None:
    """The haul metric takes the worst of each demand vertex's miles to its nearest node."""
    pops = {
        "node_w": pop("node_w", 40.0, -100.0),
        "node_e": pop("node_e", 40.0, -80.0),
        "near": access("near", 40.0, -99.0),
        "far": access("far", 40.0, -90.0),
    }
    far_miles = haversine_miles(pops["far"], pops["node_w"])
    result = demand_haul_miles(("node_w", "node_e"), [pops["near"], pops["far"]], pops)
    assert result == pytest.approx(far_miles)


def test_coverage_worst_haul_ignores_exempt_sites() -> None:
    """The coverage stop signal skips sites marked exempt from the distance constraint."""
    pops = {"node": pop("node", 40.0, -100.0)}
    near = access("near", 40.0, -99.0)
    far = replace(access("far", 10.0, -160.0), exempt_from_distance_constraint=True)
    assert coverage_worst_haul(("node",), [near, far], pops) == pytest.approx(
        haversine_miles(near, pops["node"])
    )


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
    inputs = _inputs_from_edges(
        ["c1", "c2", "z", "y"], edges, {"c1", "c2", "z"}, [access("s", 0.0, 0.05)]
    )
    hauls = coverage_candidate_hauls(("c1", "c2"), ["z"], inputs, _plan([]), {
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
# Every candidate and every demand vertex wires to both base nodes, so each grown set is a
# biconnected triangle that builds and every site homes. Geography alone decides the ranking.
_RANKING_EDGES = physical(
    {
        ("b1", "b2"): 1.0,
        **{
            (name, base): 1.0
            for name in ("east", "west", "oversea", "far", "near1", "near2", "near3", "oconus")
            for base in ("b1", "b2")
        },
    }
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


def _ranking_hauls(candidates: list[str], sites: list[Vertex]) -> list[tuple[float, str]]:
    """Score each candidate over the ranking geometry against the given demand."""
    inputs = _inputs_from_edges(
        _RANKING_IDS, _RANKING_EDGES, set(_RANKING_IDS), sites, _RANKING_COORDS
    )
    return coverage_candidate_hauls(
        ("b1", "b2"), candidates, inputs, _plan(_RANKING_IDS),
        {carrier.id: carrier for carrier in inputs.carrier_pops},
    )


def test_the_candidate_that_closes_the_gap_outranks_the_one_that_shortens_the_rest() -> None:
    """The round opened on the far site, so the node that reaches it is the one that wins."""
    assert min(_ranking_hauls(["east", "west"], _RANKING_SITES))[1] == "east"


def test_a_site_exempt_from_the_target_cannot_sway_which_candidate_wins() -> None:
    """A candidate that only helps the exempt site helps nothing the round is about."""
    assert min(_ranking_hauls(["east", "oversea"], [*_RANKING_SITES, _OCONUS_SITE]))[1] == "east"


# Fiber where spans and independent routes disagree. Three base nodes sit in a triangle.
# "rich" and "rich_far" reach all three directly, so each holds three links that fail
# independently. "poor" and "poor_far" reach two directly and spend their third span on a
# stub that rejoins the backbone at b1, so that third route can only re-cross a city they
# already depend on and each holds two. Three spans apiece either way, which is the number a
# raw span count would rank them by and the reason it is the wrong number to rank them by.
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
# the target, and again the worse-connected one is nearer.
_BOTH_COVER = [(0.0, "poor"), (6.9, "rich")]
_NEITHER_COVERS = [(103.6, "poor_far"), (138.2, "rich_far")]


def _seated(improving: list[tuple[float, str]]) -> str:
    """Which of these candidates the growth step seats over the fiber above, at 50 miles."""
    return best_coverage_candidate(improving, _FIBER_BACKBONE, _FIBER_ADJACENCY, 50.0)


def test_the_better_connected_of_two_covering_candidates_is_seated() -> None:
    """Coverage is answered by both, so the one whose fiber carries more links wins."""
    assert _seated(_BOTH_COVER) == "rich"


def test_a_candidates_spans_are_not_counted_as_independent_routes() -> None:
    """Three spans leave poor, and two independent routes out are all its own fiber allows."""
    assert candidate_mesh_ceiling("poor", _FIBER_BACKBONE, _FIBER_ADJACENCY) == 2


def test_the_nearest_candidate_is_seated_when_none_satisfies_the_target() -> None:
    """No candidate answers the round, so the gap is closed as far as it can be instead."""
    assert _seated(_NEITHER_COVERS) == "poor_far"
