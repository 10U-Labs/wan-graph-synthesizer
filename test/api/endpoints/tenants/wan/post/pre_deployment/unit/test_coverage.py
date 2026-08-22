from __future__ import annotations

from dataclasses import replace

import pytest

import fixtures
from fixtures import synthesis_inputs_from_links, search_plan
from synthesizer.input_graph import FiberSegment, Site, haversine_miles
from synthesizer.graphs import build_adjacency
from synthesizer.model import SynthesisParams, Tuning
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
physical = fixtures.fiber_segments_from
access = fixtures.access_site


def _wired_to_base(names: tuple[str, ...]) -> dict[tuple[str, str], FiberSegment]:
    return physical(
        {
            ("b1", "b2"): 1.0,
            **{(name, base): 1.0 for name in names for base in ("b1", "b2")},
        }
    )


def test_demand_hauls_report_each_site_by_its_nearest_node() -> None:
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
    pops = {"node": pop("node", 40.0, -100.0)}
    near = access("near", 40.0, -99.0)
    far = replace(access("far", 10.0, -160.0), exempt_from_distance_constraint=True)
    assert coverage_haul_profile(("node",), [near, far], pops) == pytest.approx(
        (haversine_miles(near, pops["node"]),)
    )


def test_an_all_exempt_synthesis_has_no_worst_haul() -> None:
    assert coverage_worst_haul(()) == 0.0


def test_coverage_candidate_hauls_drops_an_infeasible_addition() -> None:
    links = physical(
        {
            ("c1", "c2"): 1.0, ("s", "c1"): 1.0, ("s", "c2"): 1.0, ("z", "y"): 1.0,
        }
    )
    inputs = synthesis_inputs_from_links(
        ["c1", "c2", "z", "y"], links, {"c1", "c2", "z"}, [access("s", 0.0, 0.05)]
    )
    hauls = coverage_candidate_hauls(("c1", "c2"), ["z"], inputs, search_plan([]), {
        "c1": pop("c1", 0.0, 0.0), "c2": pop("c2", 0.0, 0.1), "z": pop("z", 0.0, 0.2)
    })
    assert not hauls


_RANKING_LINKS = _wired_to_base(
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
_OCONUS_SITE = replace(access("oconus", 0.0, -40.0), exempt_from_distance_constraint=True)


def _ranking_hauls(
    candidates: list[str], sites: list[Site]
) -> list[tuple[tuple[float, ...], str]]:
    inputs = synthesis_inputs_from_links(
        _RANKING_IDS, _RANKING_LINKS, set(_RANKING_IDS), sites, _RANKING_COORDS
    )
    return coverage_candidate_hauls(
        ("b1", "b2"), candidates, inputs, search_plan(_RANKING_IDS),
        {carrier.id: carrier for carrier in inputs.carrier_pops},
    )


def test_the_candidate_that_closes_the_gap_outranks_the_one_that_shortens_the_rest() -> None:
    assert min(_ranking_hauls(["east", "west"], _RANKING_SITES))[1] == "east"


def test_a_site_exempt_from_the_target_cannot_sway_which_candidate_wins() -> None:
    assert min(_ranking_hauls(["east", "oversea"], [*_RANKING_SITES, _OCONUS_SITE]))[1] == "east"


_FIBER_SEGMENTS = physical({
    ("b1", "b2"): 1.0, ("b2", "b3"): 1.0, ("b1", "b3"): 1.0,
    ("poor", "x"): 1.0, ("x", "b1"): 1.0, ("poor_far", "x2"): 1.0, ("x2", "b1"): 1.0,
    **{(name, base): 1.0 for name in ("rich", "rich_far") for base in ("b1", "b2", "b3")},
    **{(name, base): 1.0 for name in ("poor", "poor_far") for base in ("b1", "b2")},
})
_FIBER_ADJACENCY = build_adjacency(_FIBER_SEGMENTS)
_FIBER_BACKBONE = ("b1", "b2", "b3")
_BOTH_COVER: list[tuple[tuple[float, ...], str]] = [((0.0,), "poor"), ((6.9,), "rich")]
_NEITHER_COVERS: list[tuple[tuple[float, ...], str]] = [
    ((103.6,), "poor_far"), ((138.2,), "rich_far"),
]


def _seated(improving: list[tuple[tuple[float, ...], str]]) -> str:
    return best_coverage_candidate(improving, _FIBER_BACKBONE, _FIBER_ADJACENCY, 50.0)


def test_the_better_connected_of_two_covering_candidates_is_seated() -> None:
    assert _seated(_BOTH_COVER) == "rich"


def test_a_candidates_segments_are_not_counted_as_independent_paths() -> None:
    assert candidate_mesh_ceiling("poor", _FIBER_BACKBONE, _FIBER_ADJACENCY) == 2


def test_the_nearest_candidate_is_seated_when_none_satisfies_the_target() -> None:
    assert _seated(_NEITHER_COVERS) == "poor_far"


_GROWTH_COORDS = {
    "b1": (0.0, 0.0), "b2": (0.05, 0.0),
    "cape": (0.0, 7.4), "plains": (0.0, -7.39), "twin": (0.0, 0.0),
}
_GROWTH_IDS = ["b1", "b2", "cape", "plains", "twin"]
_GROWTH_LINKS = _wired_to_base(("cape", "plains", "twin", "east_site", "west_site"))
_GROWTH_SITES = [access("east_site", 0.0, 7.5), access("west_site", 0.0, -7.49)]


def _grown(candidates: list[str], target_miles: int) -> tuple[str, ...]:
    inputs = synthesis_inputs_from_links(
        _GROWTH_IDS, _GROWTH_LINKS, set(_GROWTH_IDS), _GROWTH_SITES, _GROWTH_COORDS
    )
    plan = search_plan(candidates)
    params = SynthesisParams(
        min_backbone_count=2, tuning=Tuning(backbone_coverage_target_miles=target_miles)
    )
    grown = grow_backbone_for_coverage(
        ("b1", "b2"), inputs, plan, params,
        {carrier.id: carrier for carrier in inputs.carrier_pops},
    )
    return tuple(sorted(grown.backbone_ids))


def test_growth_continues_when_the_two_worst_sites_are_a_hub_apart_each() -> None:
    assert _grown(_GROWTH_IDS, 100) == ("b1", "b2", "cape", "plains")


def test_growth_stops_when_no_candidate_leaves_any_site_nearer() -> None:
    assert _grown(["b1", "b2", "twin"], 100) == ("b1", "b2")


_REPORT_POPS = {"hub": pop("hub", 40.0, -100.0)}
_REPORT_SITES = [access("near", 40.0, -100.5), access("far", 40.0, -95.0)]


def _report(target_miles: float) -> CoverageReport:
    return coverage_report(("hub",), _REPORT_SITES, _REPORT_POPS, target_miles)


def test_a_synthesis_that_stopped_short_reports_the_target_unmet() -> None:
    assert _report(100.0)["met"] is False


def test_a_synthesis_inside_the_target_reports_it_met() -> None:
    assert _report(400.0)["met"] is True


def test_the_report_counts_the_sites_left_outside_the_target() -> None:
    assert _report(100.0)["sites_above_target"] == 1


def test_the_report_carries_the_worst_haul_it_measured() -> None:
    assert _report(100.0)["worst_haul_miles"] == round(
        haversine_miles(_REPORT_SITES[1], _REPORT_POPS["hub"]), 1
    )


def test_the_report_echoes_the_target_it_was_measured_against() -> None:
    assert _report(100.0)["target_miles"] == 100.0
