from __future__ import annotations

import pytest

import fixtures
from synthesizer import linear_program
from synthesizer.ceiling import BackupPathLimit
from synthesizer.graphs import adjacency_by_carrier, build_adjacency, distances_from
from synthesizer.model import SynthesisArtifacts, Tuning
from synthesizer.survivable import FiberInputs, choose_fiber

_SITES = ("w", "x", "y", "z")
_ASKED_FOR = 2
_SEGMENTS = {
    ("w", "x"): 100.0, ("x", "y"): 100.0, ("y", "z"): 100.0, ("z", "w"): 100.0,
    ("w", "y"): 250.0, ("x", "z"): 250.0,
}
ARTIFACTS = fixtures.synthesis_over_segments(_SITES, _SEGMENTS, _ASKED_FOR)
_MESH = fixtures.mesh_paths(ARTIFACTS)


def test_the_delivered_synthesis_orders_the_four_hundred_miles_the_ring_costs() -> None:
    assert ARTIFACTS.synthesis.metrics.physical_miles == 400.0


def test_the_delivered_synthesis_draws_one_path_a_pair_round_the_ring() -> None:
    assert sum(use.distance_miles for use in _MESH) == 400.0


def test_the_delivered_synthesis_publishes_the_floor_it_is_judged_against() -> None:
    assert round(ARTIFACTS.synthesis.metrics.backbone_lower_bound_miles, 3) == 400.0


def test_the_delivered_synthesis_runs_no_further_than_twice_that_floor() -> None:
    assert (
        ARTIFACTS.synthesis.metrics.physical_miles
        <= 2 * ARTIFACTS.synthesis.metrics.backbone_lower_bound_miles
    )


def test_every_site_still_holds_the_two_ways_out_it_was_owed() -> None:
    assert ARTIFACTS.validation["backbone_mesh_independence_deficient"] == []


def _many_pass_artifacts() -> SynthesisArtifacts:
    return fixtures.synthesis_over_segments(
        fixtures.MANY_PASS_SITES,
        fixtures.MANY_PASS_SEGMENTS,
        _ASKED_FOR,
        transit_ids=fixtures.MANY_PASS_TRANSIT,
    )


MANY_PASS_ARTIFACTS = _many_pass_artifacts()


def test_a_synthesis_whose_search_takes_many_passes_orders_the_fewest_miles_there_are() -> None:
    assert MANY_PASS_ARTIFACTS.synthesis.metrics.physical_miles == fixtures.MANY_PASS_MILES


def test_that_synthesis_orders_exactly_the_floor_it_publishes_rather_than_twice_it() -> None:
    assert MANY_PASS_ARTIFACTS.synthesis.metrics.physical_miles == pytest.approx(
        MANY_PASS_ARTIFACTS.synthesis.metrics.backbone_lower_bound_miles
    )


def test_every_seat_on_that_synthesis_holds_the_two_ways_out_it_was_owed() -> None:
    assert MANY_PASS_ARTIFACTS.validation["backbone_mesh_independence_deficient"] == []


def test_that_synthesis_is_the_same_synthesis_when_every_pass_of_its_search_gives_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(linear_program, "_SECONDS_A_PASS_MAY_RUN", 0.0)
    assert _many_pass_artifacts().synthesis.metrics.physical_miles == fixtures.MANY_PASS_MILES


_SPLIT_SITES = ("w", "x")
_SPLIT_TRANSIT = ("p", "q")
_SPLIT_SEGMENTS: dict[tuple[str, str], tuple[float, tuple[str, ...]]] = {
    ("w", "p"): (100.0, ("lumen",)),
    ("p", "x"): (100.0, ("lumen",)),
    ("w", "q"): (150.0, ("zayo",)),
    ("q", "x"): (150.0, ("lumen",)),
}
SPLIT_ARTIFACTS = fixtures.synthesis_over_owned_fiber(
    _SPLIT_SITES, _SPLIT_SEGMENTS, _ASKED_FOR, _SPLIT_TRANSIT
)
SPLIT_ASKED_ONE_ARTIFACTS = fixtures.synthesis_over_owned_fiber(
    _SPLIT_SITES, _SPLIT_SEGMENTS, 1, _SPLIT_TRANSIT
)
_SLACK = 1e-6


def test_no_synthesis_runs_fewer_miles_than_the_floor_it_publishes() -> None:
    assert SPLIT_ARTIFACTS.synthesis.metrics.physical_miles >= (
        SPLIT_ARTIFACTS.synthesis.metrics.backbone_lower_bound_miles - _SLACK
    )


def test_a_site_whose_ways_out_are_split_between_carriers_is_floored_at_what_it_can_buy(
) -> None:
    assert SPLIT_ARTIFACTS.synthesis.metrics.backbone_lower_bound_miles == pytest.approx(
        SPLIT_ASKED_ONE_ARTIFACTS.synthesis.metrics.backbone_lower_bound_miles
    )


SELLABLE_ARTIFACTS = fixtures.synthesis_over_owned_fiber(
    fixtures.SELLABLE_WAYS_SITES,
    fixtures.SELLABLE_WAYS_SEGMENTS,
    _ASKED_FOR,
    fixtures.SELLABLE_WAYS_TRANSIT,
)


def _fiber_the_choice_selected() -> frozenset[tuple[str, str]]:
    distances = distances_from(
        build_adjacency(fixtures.SELLABLE_WAYS_LINKS),
        sorted({city for pair in fixtures.SELLABLE_WAYS_LINKS for city in pair}),
    )
    return choose_fiber(FiberInputs(
        fixtures.SELLABLE_WAYS_SITES, fixtures.SELLABLE_WAYS_LINKS, distances,
        _ASKED_FOR, len(fixtures.SELLABLE_WAYS_SITES),
        BackupPathLimit(Tuning().backbone_max_backup_path_multiple, distances),
        adjacency_by_carrier(fixtures.SELLABLE_WAYS_LINKS),
    )).segments


def test_the_delivered_synthesis_orders_only_fiber_the_choice_selected_for_it() -> None:
    assert set(SELLABLE_ARTIFACTS.synthesis.fiber_segment_keys) <= _fiber_the_choice_selected()
