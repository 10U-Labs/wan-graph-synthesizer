"""Unit tests for the published pairs carrying more routes than their tenant bought.

The helper counts the routes a published network draws between each pair of backbone sites
and reports the pairs above the tenant's number of diverse paths. Nothing outside the build
could ask this before, and the reason to ask it is that every other published measurement
judges one route at a time: a network can hold five routes between two sites with every one
of them the shortest way over its own fiber and inside the backup route multiple, which is
what Two-Node published (GitHub issue #58).

The tenant below buys two paths. Routes are named by their two ends only, since the helper
counts them and reads no path.

A pair served under either order of its two ends is one pair, and the case is tested
because the published collections give no undertaking about which end is the source: a
helper counting the two orders apart would report a sound network as sound for the wrong
reason and miss the overbuild that is split between them.
"""

from __future__ import annotations

from typing import Any

from test_published_designs import overbuilt_pairs


def _design(pairs: list[tuple[str, str]], allowed: int = 2) -> dict[str, Any]:
    """A published network drawing one route between each pair given, in the order given."""
    return {
        "number_of_diverse_paths": allowed,
        "links": [{"source_id": source, "target_id": target} for source, target in pairs],
    }


def test_a_pair_drawn_with_more_routes_than_bought_is_reported_with_its_count() -> None:
    """Three routes where two were bought, named by the pair carrying them."""
    design = _design([("west", "east")] * 3)
    assert overbuilt_pairs(design) == [("east <-> west", 3)]


def test_a_pair_drawn_with_the_routes_it_bought_is_not_reported() -> None:
    """Two routes and two paths bought is the network the tenant asked for."""
    assert not overbuilt_pairs(_design([("west", "east")] * 2))


def test_a_pair_drawn_with_fewer_routes_than_bought_is_not_reported() -> None:
    """A pair below its number is a shortfall, which is a different report."""
    assert not overbuilt_pairs(_design([("west", "east")]))


def test_routes_served_under_either_order_of_the_two_ends_count_as_one_pair() -> None:
    """Three routes split across both orders are three routes between one pair."""
    design = _design([("west", "east"), ("east", "west"), ("west", "east")])
    assert overbuilt_pairs(design) == [("east <-> west", 3)]


def test_routes_between_different_pairs_are_counted_apart() -> None:
    """Two pairs at two routes each is two sound pairs, not one pair at four."""
    assert not overbuilt_pairs(
        _design([("west", "east")] * 2 + [("west", "north")] * 2)
    )


def test_every_overbuilt_pair_is_reported_not_only_the_first() -> None:
    """A network overbuilt in two places has both named, in order of the pair."""
    design = _design([("west", "east")] * 3 + [("north", "south")] * 3)
    assert [pair for pair, _count in overbuilt_pairs(design)] == [
        "east <-> west", "north <-> south"
    ]


def test_a_network_carrying_no_links_reports_nothing() -> None:
    """A tenant whose build has not landed has no routes to count and no finding to make."""
    assert not overbuilt_pairs(_design([]))
