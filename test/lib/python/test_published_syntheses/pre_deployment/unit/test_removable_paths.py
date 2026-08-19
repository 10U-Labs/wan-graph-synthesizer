"""Unit tests for the published paths whose removal would cost nobody anything.

The helper reads a published network, takes each path out of it in turn, and reports the
ones nobody would miss: no backbone site loses a diverse path it was asked for, no site is
cut off from the rest, and no city's loss splits the fiber where none did with the path in.
54 of the 192 paths in the six published networks are of that kind, 23,917 of their 83,927
miles, and no published measurement could say so, because every one of them judged a path
on its own and a network can hold any number of unneeded paths with each of them sound
(GitHub issue #60).

Every case below is a network drawn out of runs of cities, one run per path, at a hundred
miles a hop. The square of four sites is the shape most of them are cut from: each of its
sites holds exactly the two ways out its tenant asked for, so no path of the square can go,
while a path laid across the middle of it can. The tenant buys two diverse paths
throughout, and sites and cities are named alike here because a published path lists the
cities it crosses by name and its two ends by id.

Each of the three demands a removal has to meet has a case that refuses one, because a
helper refusing every removal would report the empty list a sound network reports and the
assertion standing on it could not tell the two apart.
"""

from __future__ import annotations

from typing import Any

from test_published_syntheses import removable_paths


def _published_network(crossings: list[tuple[str, ...]]) -> dict[str, Any]:
    """A published network holding one path per run of cities given.

    Each path runs between the first and the last city of its run, both of which are
    backbone sites, and costs a hundred miles a hop, so a path round by two cities is the
    longer of two and the one reported first.
    """
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
        "backbone": [{"id": city, "name": city} for city in seated],
        "links": drawn,
    }


# Four sites in a loop, each holding the two ways out its tenant asked for and no more.
# Nothing here can go: taking any of the four paths out leaves the two sites it joined with
# one way out apiece where two were bought.
_SQUARE: list[tuple[str, ...]] = [
    ("west", "a", "north"),
    ("north", "b", "east"),
    ("east", "d", "south"),
    ("south", "f", "west"),
]

# Two paths laid across the middle of the square, from west to east. Either can go: both
# ends keep two ways out that no one city's loss takes together, the loop still joins every
# site, and the fiber left is the loop, which no city's loss splits.
_SHORT_CROSSING: tuple[str, ...] = ("west", "g", "east")
_LONG_CROSSING: tuple[str, ...] = ("west", "p", "q", "east")

# A site reached only through one city, twice over. Its tenant asked for two diverse paths
# and its fiber can never deliver them, since losing that city takes both, so the second
# path buys it nothing the first does not already give it.
_HOMED_TWICE: list[tuple[str, ...]] = [("west", "n", "deep"), ("east", "n", "deep")]

# Three sites in a loop, which is the fewest paths that give each of them two ways out.
_TRIANGLE: list[tuple[str, ...]] = [
    ("west", "a", "north"),
    ("north", "b", "up"),
    ("up", "k", "west"),
]

# A second triangle far from the first, and the one path holding the two of them together.
_FAR_TRIANGLE: list[tuple[str, ...]] = [
    ("east", "d", "south"),
    ("south", "f", "down"),
    ("down", "m", "east"),
]
_ONLY_PATH_BETWEEN_THEM: tuple[str, ...] = ("west", "h", "east")

# Two loops of fiber meeting at the city c, and a path from west to east going nowhere near
# it. Every site keeps its two ways out without that path and the sites stay one network
# without it, but the fiber left is two loops joined at one city, so losing c would cut
# west and north off from east and south.
_TWO_LOOPS: list[tuple[str, ...]] = [
    ("west", "a", "north"),
    ("east", "e", "south"),
    ("north", "c", "east"),
    ("west", "c", "south"),
    ("west", "h", "east"),
]


def test_a_path_no_site_and_no_city_would_miss_is_reported_with_the_miles_it_runs() -> None:
    """The crossing is 200 miles nobody ordered: the loop already gives everyone two ways out."""
    assert removable_paths(_published_network(_SQUARE + [_SHORT_CROSSING])) == [
        ("west -> g -> east", 200.0)
    ]


def test_every_path_nobody_needs_is_reported_and_the_longest_of_them_first() -> None:
    """Two crossings of one square are two findings, the 300-mile one ahead of the 200."""
    assert removable_paths(
        _published_network(_SQUARE + [_SHORT_CROSSING, _LONG_CROSSING])
    ) == [("west -> p -> q -> east", 300.0), ("west -> g -> east", 200.0)]


def test_a_path_a_site_would_lose_a_diverse_path_by_is_kept() -> None:
    """Three sites in a loop hold two ways out each, and one path fewer leaves two of them one."""
    assert not removable_paths(_published_network(_TRIANGLE))


def test_a_path_holding_the_two_halves_of_a_backbone_together_is_kept() -> None:
    """West and east keep their two ways out without it, and the far triangle keeps nothing.

    This is the removal the diverse-path count passes and connectivity refuses: both ends
    of the path sit in a loop of their own, so neither loses a way out it was asked for,
    and taking it out still leaves east, south and down with no path to west, north and up.
    """
    assert not removable_paths(
        _published_network(_TRIANGLE + _FAR_TRIANGLE + [_ONLY_PATH_BETWEEN_THEM])
    )


def test_a_path_whose_removal_would_leave_a_city_splitting_the_fiber_is_kept() -> None:
    """Without it the fiber is two loops meeting at c, so losing c would take half the network.

    The removal the first two demands pass and the third refuses: every site still holds
    the two ways out it bought, the four sites are still one network over the paths that
    remain, and the only thing lost is the one way from the loop holding west and north
    to the loop holding east and south that does not cross c.
    """
    assert not removable_paths(_published_network(_TWO_LOOPS))


def test_fiber_that_already_splits_at_a_city_keeps_no_path_that_buys_nothing() -> None:
    """Deep is reached through n whichever path is taken, so its second path buys it nothing.

    The demand about single points of failure asks whether a removal makes one, not whether
    the synthesis has one, so it cannot refuse a removal from fiber that already fails a city's
    loss. Losing n cuts deep off with both paths in place, and each of the two is reported
    because each is judged with the other still there.
    """
    assert removable_paths(_published_network(_SQUARE + _HOMED_TWICE)) == [
        ("east -> n -> deep", 200.0), ("west -> n -> deep", 200.0)
    ]


def test_a_network_carrying_no_paths_reports_nothing() -> None:
    """A tenant whose build has not landed has no path to take out and no finding to make."""
    assert not removable_paths(_published_network([]))
