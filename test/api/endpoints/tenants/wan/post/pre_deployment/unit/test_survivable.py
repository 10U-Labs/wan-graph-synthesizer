from __future__ import annotations

import pytest

import fixtures
from synthesizer.ceiling import (
    BackupPathLimit,
    PathProofInputs,
    diverse_path_ceilings,
)
from synthesizer.graphs import adjacency_by_carrier, build_adjacency, distances_from
from synthesizer.input_graph import FiberSegment
from synthesizer.survivable import (
    FiberChoice,
    FiberInputs,
    _held,
    _requirements,
    _shortfalls,
    _ways_out_rows,
    _writing,
    admissible_fiber,
    choose_fiber,
)

physical = fixtures.fiber_segments_from

_WAYS_OUT = 2
_SLACK = 1e-6


def _all_distances(
    links: dict[tuple[str, str], FiberSegment]
) -> dict[str, dict[str, float]]:
    cities = sorted({city for pair in links for city in pair})
    return distances_from(build_adjacency(links), cities)


def _asking(
    links: dict[tuple[str, str], FiberSegment],
    backbone_ids: tuple[str, ...],
    seat_cap: int | None = None,
    ways_out: int = _WAYS_OUT,
) -> FiberInputs:
    return FiberInputs(
        backbone_ids, links, _all_distances(links), ways_out, seat_cap, None,
        adjacency_by_carrier(links),
    )


def _chosen(
    links: dict[tuple[str, str], FiberSegment],
    backbone_ids: tuple[str, ...],
    seat_cap: int | None = None,
    ways_out: int = _WAYS_OUT,
) -> FiberChoice:
    return choose_fiber(_asking(links, backbone_ids, seat_cap, ways_out))


def _owed(
    links: dict[tuple[str, str], FiberSegment],
    backbone_ids: tuple[str, ...],
    site: str,
    seat_cap: int | None = None,
) -> int:
    inputs = _asking(links, backbone_ids, seat_cap)
    fiber = admissible_fiber(inputs)
    return sum(
        row.required for row in _ways_out_rows(site, _writing(inputs, fiber)).together
    )


def _selected_miles(
    choice: FiberChoice, links: dict[tuple[str, str], FiberSegment]
) -> float:
    return sum(links[segment].distance_miles for segment in choice.segments)


_CROSSING_SITES = ("eug", "hil", "sea")
_CROSSING_DISTANCES = _all_distances(fixtures.CROSSING_LINKS)
_OVERLAND = frozenset({("eug", "pdx"), ("hil", "pdx"), ("pdx", "sea")})
_EVERY_CROSSING_SEGMENT = frozenset(fixtures.CROSSING_LINKS)


def _admissible(multiple: float | None) -> frozenset[tuple[str, str]]:
    limit = None if multiple is None else BackupPathLimit(multiple, _CROSSING_DISTANCES)
    return frozenset(admissible_fiber(FiberInputs(
        _CROSSING_SITES, fixtures.CROSSING_LINKS, _CROSSING_DISTANCES, _WAYS_OUT, None, limit
    )))


def test_with_no_bound_in_hand_every_segment_the_carrier_has_is_admissible() -> None:
    assert _admissible(None) == _EVERY_CROSSING_SEGMENT


def test_fiber_no_admissible_path_could_run_over_is_left_out_of_the_choice() -> None:
    assert _admissible(3.0) == _OVERLAND


def test_a_multiple_wide_enough_for_the_crossing_keeps_the_crossing() -> None:
    assert _admissible(1000.0) == _EVERY_CROSSING_SEGMENT


_NO_FIBER = _chosen(physical({}), ("a", "b"))
_NO_SITES = _chosen(physical({("a", "b"): 1.0}), ())


def test_a_backbone_with_no_fiber_at_all_buys_nothing_and_is_floored_at_nothing() -> None:
    assert _NO_FIBER == FiberChoice(frozenset(), 0.0)


def test_a_backbone_with_no_sites_selects_none_of_the_fiber_in_front_of_it() -> None:
    assert not _NO_SITES.segments


def test_a_backbone_with_no_sites_is_floored_at_nothing_rather_than_at_what_is_on_offer() -> None:
    assert _NO_SITES.lower_bound_miles == pytest.approx(0.0)


_RING_PAIRS = {("a", "b"): 1.0, ("b", "c"): 1.0, ("c", "d"): 1.0, ("a", "d"): 1.0}
_RING_SITES = ("a", "b", "c", "d")
_RING_SEGMENTS = frozenset(_RING_PAIRS)
_RING = physical(_RING_PAIRS)
_CHORD = physical({**_RING_PAIRS, ("a", "c"): 10.0})
_RING_CHOICE = _chosen(_RING, _RING_SITES)
_CHORD_CHOICE = _chosen(_CHORD, _RING_SITES)


def test_a_ring_is_selected_whole_because_nothing_short_of_it_gives_two_ways_out() -> None:
    assert _RING_CHOICE.segments == _RING_SEGMENTS


def test_the_floor_under_the_ring_is_the_mileage_of_the_ring_itself() -> None:
    assert _RING_CHOICE.lower_bound_miles == pytest.approx(4.0)


def test_fiber_no_requirement_turns_on_is_left_where_it_is() -> None:
    assert _CHORD_CHOICE.segments == _RING_SEGMENTS


_CHAIN = physical({("a", "b"): 1.0, ("b", "c"): 1.0})
_CHAIN_CHOICE = _chosen(_CHAIN, ("a", "b", "c"))


def test_a_site_behind_a_single_point_of_failure_is_asked_for_what_its_fiber_can_carry() -> None:
    assert _CHAIN_CHOICE.segments == frozenset(_CHAIN)


_TWIN_WAYS = physical({
    ("a", "p"): 1.0, ("b", "p"): 1.0, ("a", "q"): 1.0, ("b", "q"): 1.0,
})
_TWIN_CHOICE = _chosen(_TWIN_WAYS, ("a", "b"), seat_cap=2)


def test_a_pair_allowed_two_ways_between_them_is_given_both_ways_round() -> None:
    assert _TWIN_CHOICE.segments == frozenset(_TWIN_WAYS)


_TWIN_SPLIT = fixtures.carrier_fiber_segments({
    ("a", "p"): (1.0, ("zayo",)),
    ("b", "p"): (1.0, ("zayo",)),
    ("a", "q"): (1.0, ("zayo",)),
    ("b", "q"): (1.0, ("lumen",)),
})
_TWIN_OWNED = fixtures.carrier_fiber_segments({
    ("a", "p"): (1.0, ("zayo",)),
    ("b", "p"): (1.0, ("zayo",)),
    ("a", "q"): (1.0, ("lumen",)),
    ("b", "q"): (1.0, ("lumen",)),
})
_TWIN_SPLIT_CHOICE = _chosen(_TWIN_SPLIT, ("a", "b"), seat_cap=2)
_TWIN_SPLIT_ASKED_ONE = _chosen(_TWIN_SPLIT, ("a", "b"), seat_cap=2, ways_out=1)


def test_a_site_is_owed_only_the_ways_out_one_carrier_can_sell() -> None:
    assert _owed(_TWIN_SPLIT, ("a", "b"), "a", seat_cap=2) == 1


def test_a_site_is_owed_both_ways_out_where_one_carrier_has_each() -> None:
    assert _owed(_TWIN_OWNED, ("a", "b"), "a", seat_cap=2) == 2


def test_fiber_nobody_owns_is_owed_to_every_carrier() -> None:
    assert _owed(_TWIN_WAYS, ("a", "b"), "a", seat_cap=2) == 2


def test_the_floor_is_measured_over_the_requirements_the_build_is_held_to() -> None:
    assert _TWIN_SPLIT_CHOICE.lower_bound_miles == pytest.approx(
        _TWIN_SPLIT_ASKED_ONE.lower_bound_miles
    )


_TWO_TRIANGLES = physical({
    ("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0,
    ("d", "e"): 1.0, ("e", "f"): 1.0, ("d", "f"): 1.0,
    ("c", "d"): 1.0,
})
_TRIANGLE_SITES = ("a", "b", "c", "d", "e", "f")
_TRIANGLES_CHOICE = _chosen(_TWO_TRIANGLES, _TRIANGLE_SITES)


def test_the_segment_the_first_answer_missed_is_selected_once_it_is_written_down() -> None:
    assert ("c", "d") in _TRIANGLES_CHOICE.segments


_SELLABLE = frozenset({("a", "r"), ("b", "r")})


def test_the_fiber_selected_is_fiber_one_carrier_can_sell_a_whole_path_over() -> None:
    assert _chosen(
        fixtures.SELLABLE_WAYS_LINKS, fixtures.SELLABLE_WAYS_SITES, seat_cap=2
    ).segments == _SELLABLE


_NEAR_AND_FAR_DISTANCES = _all_distances(fixtures.NEAR_AND_FAR_LINKS)


def _fiber_the_row_toward(
    links: dict[tuple[str, str], FiberSegment],
    backbone_ids: tuple[str, ...],
    limit: BackupPathLimit,
    site: str,
    peer: str,
) -> frozenset[tuple[str, str]]:
    inputs = FiberInputs(
        backbone_ids, links, _all_distances(links), _WAYS_OUT, None, limit,
        adjacency_by_carrier(links),
    )
    writing = _writing(inputs, admissible_fiber(inputs))
    return frozenset(
        segment
        for row in _ways_out_rows(site, writing).toward_each
        if row.peers == frozenset({peer})
        for segment in row.over
    )


def test_a_way_round_past_the_bound_is_not_selected_for_the_pair_it_is_past_it_for() -> None:
    assert _fiber_the_row_toward(
        fixtures.NEAR_AND_FAR_LINKS,
        fixtures.NEAR_AND_FAR_SITES,
        BackupPathLimit(3.0, _NEAR_AND_FAR_DISTANCES),
        "a",
        "b",
    ) == frozenset({("a", "b")})


_DISTANT_PEER_SITES = ("hil", "sea", "syd")
_DISTANT_PEER_DISTANCES = _all_distances(fixtures.DISTANT_PEER_LINKS)
_DISTANT_PEER_LIMIT = BackupPathLimit(3.0, _DISTANT_PEER_DISTANCES)
_DISTANT_PEER_CHOICE = choose_fiber(FiberInputs(
    _DISTANT_PEER_SITES, fixtures.DISTANT_PEER_LINKS, _DISTANT_PEER_DISTANCES,
    _WAYS_OUT, None, _DISTANT_PEER_LIMIT,
    adjacency_by_carrier(fixtures.DISTANT_PEER_LINKS),
))


def _distant_peer_ceilings(segments: frozenset[tuple[str, str]]) -> dict[str, int]:
    return diverse_path_ceilings(PathProofInputs(
        _DISTANT_PEER_SITES,
        build_adjacency({
            segment: fixtures.DISTANT_PEER_LINKS[segment] for segment in segments
        }),
        _DISTANT_PEER_LIMIT,
        _WAYS_OUT,
    ))


def test_the_fiber_selected_for_a_site_carries_every_way_out_its_fiber_carries() -> None:
    assert _distant_peer_ceilings(_DISTANT_PEER_CHOICE.segments) == _distant_peer_ceilings(
        frozenset(fixtures.DISTANT_PEER_LINKS)
    ) == {"hil": 2, "sea": 1, "syd": 2}


_MANY_PASS = physical(fixtures.MANY_PASS_SEGMENTS)
_MANY_PASS_INPUTS = _asking(_MANY_PASS, fixtures.MANY_PASS_SITES)
_MANY_PASS_CHOICE = _chosen(_MANY_PASS, fixtures.MANY_PASS_SITES)
_MANY_PASS_FIBER = admissible_fiber(_MANY_PASS_INPUTS)


def test_a_search_that_runs_long_enough_buys_the_shortest_synthesis_there_is() -> None:
    assert _selected_miles(_MANY_PASS_CHOICE, _MANY_PASS) == pytest.approx(
        _MANY_PASS_CHOICE.lower_bound_miles
    )


def test_the_fiber_a_long_search_settles_on_meets_every_requirement_asked_of_it() -> None:
    assert not _shortfalls(
        _requirements(_MANY_PASS_INPUTS, _MANY_PASS_FIBER),
        _held(_MANY_PASS_FIBER, _MANY_PASS_CHOICE.segments),
    )


_CASES: tuple[tuple[str, FiberChoice, dict[tuple[str, str], FiberSegment]], ...] = (
    ("ring", _RING_CHOICE, _RING),
    ("ring and chord", _CHORD_CHOICE, _CHORD),
    ("chain", _CHAIN_CHOICE, _CHAIN),
    ("two triangles", _TRIANGLES_CHOICE, _TWO_TRIANGLES),
    ("pair with two ways round", _TWIN_CHOICE, _TWIN_WAYS),
    ("pair whose second way round changes hands", _TWIN_SPLIT_CHOICE, _TWIN_SPLIT),
    ("twelve cities and five seats", _MANY_PASS_CHOICE, _MANY_PASS),
)


def test_no_choice_is_floored_above_the_fiber_it_actually_selected() -> None:
    assert [
        name
        for name, choice, links in _CASES
        if choice.lower_bound_miles > _selected_miles(choice, links) + _SLACK
    ] == []
