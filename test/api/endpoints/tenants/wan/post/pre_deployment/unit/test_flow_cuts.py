from __future__ import annotations

from collections.abc import Mapping

from synthesizer.flow_cuts import Separation, SeparationQuestion, weakest_separation
from synthesizer.input_graph import link_key

_SITE = "a"
_ONE_PEER = frozenset({"b"})
_TWO_PEERS = frozenset({"b", "c"})
_NOTHING_SPARED: frozenset[str] = frozenset()

_NOTHING_TO_SELECT = Separation(frozenset(), frozenset())
_ONLY_THE_SEGMENT = Separation(frozenset(), frozenset({("a", "b")}))
_ONLY_THE_CITY = Separation(frozenset({"x"}), frozenset())


def _whole(*segments: tuple[str, str]) -> dict[tuple[str, str], float]:
    return {link_key(left, right): 1.0 for left, right in segments}


def _asked(
    held: Mapping[tuple[str, str], float],
    required: int,
    peers: frozenset[str] = _ONE_PEER,
    spared: frozenset[str] = _NOTHING_SPARED,
) -> Separation | None:
    return weakest_separation(SeparationQuestion(_SITE, peers, spared, held), required)


_DIRECT = _whole(("a", "b"))

_PART_SELECTED: Mapping[tuple[str, str], float] = {("a", "b"): 0.5}
_UNSELECTED: Mapping[tuple[str, str], float] = {("a", "b"): 0.0}

_ELSEWHERE = _whole(("y", "z"))

_ROUND_ONE_CITY = _whole(("a", "x"), ("a", "p"), ("p", "x"), ("b", "x"), ("c", "x"))


def test_fiber_already_carrying_what_was_asked_reports_no_separation() -> None:
    assert _asked(_DIRECT, 1) is None


def test_asking_for_nothing_ends_before_any_searching() -> None:
    assert _asked(_DIRECT, 0) is None


def test_a_site_the_fiber_does_not_reach_has_nothing_to_buy() -> None:
    assert _asked(_ELSEWHERE, 1) == _NOTHING_TO_SELECT


def test_two_sites_joined_by_one_segment_are_separated_by_that_segment() -> None:
    assert _asked(_DIRECT, 2) == _ONLY_THE_SEGMENT


def test_a_segment_held_in_part_carries_only_that_much_of_a_way_out() -> None:
    assert _asked(_PART_SELECTED, 1) == _ONLY_THE_SEGMENT


def test_a_segment_nothing_is_held_of_is_still_the_fiber_to_select() -> None:
    assert _asked(_UNSELECTED, 1) == _ONLY_THE_SEGMENT


def test_the_city_every_way_out_crosses_is_what_the_fiber_cannot_survive() -> None:
    assert _asked(_ROUND_ONE_CITY, 2, peers=_TWO_PEERS) == _ONLY_THE_CITY


def test_sparing_that_city_leaves_the_same_fiber_carrying_both_ways_out() -> None:
    assert _asked(_ROUND_ONE_CITY, 2, peers=_TWO_PEERS, spared=frozenset({"x"})) is None


def test_a_peer_the_fiber_does_not_carry_is_left_out_of_the_count() -> None:
    assert _asked(_DIRECT, 1, peers=frozenset({"nowhere"})) == _NOTHING_TO_SELECT
