from __future__ import annotations

from typing import Any

from test_published_syntheses import overbuilt_pairs


def _link(source: str, target: str, *transit: str) -> dict[str, Any]:
    return {
        "source_id": source,
        "target_id": target,
        "path": [source, *transit, target],
        "distance_miles": 100.0 * (len(transit) + 1),
    }


def _synthesis(links: list[dict[str, Any]], allowed: int = 2) -> dict[str, Any]:
    sites = sorted({link[end] for link in links for end in ("source_id", "target_id")})
    return {
        "number_of_diverse_paths": allowed,
        "backbone": [{"id": site, "name": site} for site in sites],
        "links": links,
    }


_SPARE_PATH = [
    _link("west", "east", "m1"),
    _link("west", "east", "m2"),
    _link("west", "north", "m3"),
    _link("east", "north", "m4"),
]


def test_a_pair_holding_a_path_neither_end_needs_is_reported_with_its_count() -> None:
    assert overbuilt_pairs(_synthesis(_SPARE_PATH)) == [("east <-> west", 2)]


def test_a_pair_whose_second_path_is_a_ways_out_is_not_reported() -> None:
    synthesis = _synthesis([_link("west", "east", "m1"), _link("west", "east", "m2")])
    assert not overbuilt_pairs(synthesis)


def test_a_second_path_crossing_the_same_city_as_the_first_is_reported() -> None:
    synthesis = _synthesis([
        _link("west", "east", "m1"),
        _link("west", "east", "m1", "x"),
        _link("west", "north", "m3"),
        _link("east", "north", "m4"),
    ])
    assert overbuilt_pairs(synthesis) == [("east <-> west", 2)]


def test_a_pair_joined_once_is_not_reported() -> None:
    assert not overbuilt_pairs(_synthesis([_link("west", "east", "m1")]))


def test_paths_served_under_either_order_of_the_two_ends_count_as_one_pair() -> None:
    synthesis = _synthesis([
        _link("west", "east", "m1"),
        _link("east", "west", "m2"),
        _link("west", "east", "m5"),
        _link("west", "north", "m3"),
        _link("east", "north", "m4"),
    ])
    assert overbuilt_pairs(synthesis) == [("east <-> west", 3)]


def test_paths_between_different_pairs_are_counted_apart() -> None:
    synthesis = _synthesis([_link("west", "east", "m1"), _link("west", "north", "m3")])
    assert not overbuilt_pairs(synthesis)


def test_every_overbuilt_pair_is_reported_not_only_the_first() -> None:
    synthesis = _synthesis([
        *_SPARE_PATH,
        _link("north", "south", "m6"),
        _link("north", "south", "m7"),
        _link("west", "south", "m8"),
    ])
    assert [pair for pair, _count in overbuilt_pairs(synthesis)] == [
        "east <-> west", "north <-> south"
    ]


def test_a_network_carrying_no_links_reports_nothing() -> None:
    assert not overbuilt_pairs(_synthesis([]))
