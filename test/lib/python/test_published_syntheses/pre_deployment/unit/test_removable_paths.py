from __future__ import annotations

from typing import Any

from test_published_syntheses import removable_paths


def _published_network(
    crossings: list[tuple[str, ...]], forced: tuple[tuple[str, str], ...] = ()
) -> dict[str, Any]:
    drawn = [
        {
            "source_id": cities[0],
            "target_id": cities[-1],
            "path": list(cities),
            "distance_miles": 100.0 * (len(cities) - 1),
        }
        for cities in crossings
    ]
    seated = sorted({end for cities in crossings for end in (cities[0], cities[-1])})
    return {
        "number_of_diverse_paths": 2,
        "forced_paths": [{"source": source, "target": target} for source, target in forced],
        "backbone": [{"id": city, "name": city} for city in seated],
        "links": drawn,
    }


_SQUARE: list[tuple[str, ...]] = [
    ("west", "a", "north"),
    ("north", "b", "east"),
    ("east", "d", "south"),
    ("south", "f", "west"),
]

_SHORT_CROSSING: tuple[str, ...] = ("west", "g", "east")
_LONG_CROSSING: tuple[str, ...] = ("west", "p", "q", "east")

_HOMED_TWICE: list[tuple[str, ...]] = [("west", "n", "deep"), ("east", "n", "deep")]

_TRIANGLE: list[tuple[str, ...]] = [
    ("west", "a", "north"),
    ("north", "b", "up"),
    ("up", "k", "west"),
]

_FAR_TRIANGLE: list[tuple[str, ...]] = [
    ("east", "d", "south"),
    ("south", "f", "down"),
    ("down", "m", "east"),
]
_ONLY_PATH_BETWEEN_THEM: tuple[str, ...] = ("west", "h", "east")

_TWO_LOOPS: list[tuple[str, ...]] = [
    ("west", "a", "north"),
    ("east", "e", "south"),
    ("north", "c", "east"),
    ("west", "c", "south"),
    ("west", "h", "east"),
]


def test_a_path_no_site_and_no_city_would_miss_is_reported_with_the_miles_it_runs() -> None:
    assert removable_paths(_published_network(_SQUARE + [_SHORT_CROSSING])) == [
        ("west -> g -> east", 200.0)
    ]


def test_every_path_nobody_needs_is_reported_and_the_longest_of_them_first() -> None:
    assert removable_paths(
        _published_network(_SQUARE + [_SHORT_CROSSING, _LONG_CROSSING])
    ) == [("west -> p -> q -> east", 300.0), ("west -> g -> east", 200.0)]


def test_a_path_the_operator_pinned_is_kept_though_the_three_demands_would_let_it_go() -> None:
    assert not removable_paths(
        _published_network(_SQUARE + [_SHORT_CROSSING], (("west", "east"),))
    )


def test_a_pinned_pair_keeps_no_path_between_two_other_sites() -> None:
    assert removable_paths(
        _published_network(_SQUARE + [_SHORT_CROSSING], (("west", "north"),))
    ) == [("west -> g -> east", 200.0)]


def test_a_pinned_pair_written_the_other_way_round_is_the_same_pair() -> None:
    assert not removable_paths(
        _published_network(_SQUARE + [_SHORT_CROSSING], (("east", "west"),))
    )


def test_a_path_a_site_would_lose_a_diverse_path_by_is_kept() -> None:
    assert not removable_paths(_published_network(_TRIANGLE))


def test_a_path_holding_the_two_halves_of_a_backbone_together_is_kept() -> None:
    assert not removable_paths(
        _published_network(_TRIANGLE + _FAR_TRIANGLE + [_ONLY_PATH_BETWEEN_THEM])
    )


def test_a_path_whose_removal_would_leave_a_city_splitting_the_fiber_is_kept() -> None:
    assert not removable_paths(_published_network(_TWO_LOOPS))


def test_fiber_that_already_splits_at_a_city_keeps_no_path_that_gains_nothing() -> None:
    assert removable_paths(_published_network(_SQUARE + _HOMED_TWICE)) == [
        ("east -> n -> deep", 200.0), ("west -> n -> deep", 200.0)
    ]


def test_a_network_carrying_no_paths_reports_nothing() -> None:
    assert not removable_paths(_published_network([]))
