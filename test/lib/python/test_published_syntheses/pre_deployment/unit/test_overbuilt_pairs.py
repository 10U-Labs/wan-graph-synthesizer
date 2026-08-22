"""Unit tests for the second path between two sites that gains neither of them a way out.

The helper reads a published network and reports the pairs of backbone sites holding a path
nobody needed. Nothing outside the build could ask this before, and the reason to ask it is
that every other published measurement judges one path at a time: a network can hold five
paths between two sites with every one of them the shortest way over its own fiber and
inside the backup path multiple, which is what Two-Node published (GitHub issue #58).

What makes a second path between two sites worth its monthly cost is that a single city's
loss would not take it along with the first. So each case below is a published network drawn
one way or the other, and what separates the ones reported from the ones passed over is
whether setting the longest path between a pair aside costs one of its two ends a way out
it was asked for.

The tenant asks for two paths throughout. Sites and cities are named the same in these fixtures,
since the published links list the cities a path crosses by name and the pair by id.

A pair served under either order of its two ends is one pair, and the case is tested because
the published collections give no undertaking about which end is the source: a helper
counting the two orders apart would report a sound network as sound for the wrong reason and
miss the overbuild that is split between them.
"""

from __future__ import annotations

from typing import Any

from test_published_syntheses import overbuilt_pairs


def _link(source: str, target: str, *transit: str) -> dict[str, Any]:
    """One published path between two sites, crossing the transit cities given.

    Measured by the cities it crosses, so a path round by two cities is the longer of two and
    the one the helper sets aside.
    """
    return {
        "source_id": source,
        "target_id": target,
        "path": [source, *transit, target],
        "distance_miles": 100.0 * (len(transit) + 1),
    }


def _synthesis(links: list[dict[str, Any]], allowed: int = 2) -> dict[str, Any]:
    """A published network drawing the paths given, between the sites they name."""
    sites = sorted({link[end] for link in links for end in ("source_id", "target_id")})
    return {
        "number_of_diverse_paths": allowed,
        "backbone": [{"id": site, "name": site} for site in sites],
        "links": links,
    }


# West and east are joined twice and each of them reaches north as well, so setting either
# of the two paths aside still leaves both ends two ways out that share no city.
_SPARE_PATH = [
    _link("west", "east", "m1"),
    _link("west", "east", "m2"),
    _link("west", "north", "m3"),
    _link("east", "north", "m4"),
]


def test_a_pair_holding_a_path_neither_end_needs_is_reported_with_its_count() -> None:
    """Both ends keep the two paths they had without it, so nobody needed the second."""
    assert overbuilt_pairs(_synthesis(_SPARE_PATH)) == [("east <-> west", 2)]


def test_a_pair_whose_second_path_is_a_ways_out_is_not_reported() -> None:
    """Two sites and nobody else: without the second path each holds one path of two."""
    synthesis = _synthesis([_link("west", "east", "m1"), _link("west", "east", "m2")])
    assert not overbuilt_pairs(synthesis)


def test_a_second_path_crossing_the_same_city_as_the_first_is_reported() -> None:
    """It fails with the first, so it is a path ordered and no protection gained."""
    synthesis = _synthesis([
        _link("west", "east", "m1"),
        _link("west", "east", "m1", "x"),
        _link("west", "north", "m3"),
        _link("east", "north", "m4"),
    ])
    assert overbuilt_pairs(synthesis) == [("east <-> west", 2)]


def test_a_pair_joined_once_is_not_reported() -> None:
    """One path between two sites is what joining them costs, whatever else is going on."""
    assert not overbuilt_pairs(_synthesis([_link("west", "east", "m1")]))


def test_paths_served_under_either_order_of_the_two_ends_count_as_one_pair() -> None:
    """Three paths split across both orders are three paths between one pair."""
    synthesis = _synthesis([
        _link("west", "east", "m1"),
        _link("east", "west", "m2"),
        _link("west", "east", "m5"),
        _link("west", "north", "m3"),
        _link("east", "north", "m4"),
    ])
    assert overbuilt_pairs(synthesis) == [("east <-> west", 3)]


def test_paths_between_different_pairs_are_counted_apart() -> None:
    """Two pairs at one path each is two sound pairs, not one pair at two."""
    synthesis = _synthesis([_link("west", "east", "m1"), _link("west", "north", "m3")])
    assert not overbuilt_pairs(synthesis)


def test_every_overbuilt_pair_is_reported_not_only_the_first() -> None:
    """A network overbuilt in two places has both named, in order of the pair."""
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
    """A tenant whose build has not landed has no paths to count and no finding to make."""
    assert not overbuilt_pairs(_synthesis([]))
