"""Unit tests for the cities whose loss would leave a published network in pieces.

The helper reads the hops of every published path, drops one city at a time, and reports the
ones the rest of the network cannot get past. That is the whole of what a tenant buying two
ways out of every backbone node is paying for, and it is a property no site can hold on its
own: three of the five live tenants published a network some one city's loss broke in two,
with DAF's falling apart on any of eleven cities (GitHub issue #112).

Every case below is a network drawn out of runs of cities, one run per path, and only the
hops matter here -- what a city's loss costs is decided by the fiber the paths run over and
by nothing else about them. Four shapes cover the answers there are: a network no city's
loss touches, one a single city carries, one two cities each carry, and one that is in
pieces before any city is lost at all.
"""

from __future__ import annotations

from typing import Any

from test_published_syntheses import cut_cities


def _published_paths(crossings: list[tuple[str, ...]]) -> list[dict[str, Any]]:
    """The published paths of a network crossing the runs of cities given, one run a path.

    A published path names the cities it crosses in the order it crosses them, and those
    hops are the whole of what a city's loss is asked about: they are the fiber the operator
    ordered. Which two sites a path was drawn for decides nothing here and is left out.
    """
    return [{"path": list(cities)} for cities in crossings]


# Four sites in a loop. Every city on it has two ways round to every other, so nothing here
# is anybody's only way anywhere.
_RING = _published_paths([
    ("west", "a", "north"),
    ("north", "b", "east"),
    ("east", "d", "south"),
    ("south", "f", "west"),
])

# Two triangles sharing the city ``waist`` and touching nowhere else. Each site keeps its own
# two ways out inside its own triangle, and the day ``waist`` goes dark the two triangles
# cannot reach each other at all. This is the shape the three live tenants published.
_BOWTIE = _published_paths([
    ("west", "a", "waist"),
    ("waist", "b", "west"),
    ("east", "c", "waist"),
    ("waist", "d", "east"),
])

# Four cities in a line. Losing either of the two in the middle leaves the two ends with no
# way to each other, and the network's own ends carry nothing but themselves.
_CHAIN = _published_paths([("west", "middle", "centre", "east")])

# Two paths that share no city, which is a network that is already two networks. Nothing a
# city's loss does to it can make it any more broken than it is.
_APART = _published_paths([("west", "a", "north"), ("east", "b", "south")])


def test_a_network_no_city_carries_names_nobody() -> None:
    """A loop gives every city a second way round, so no city's loss splits it."""
    assert cut_cities(_RING) == []


def test_a_network_one_city_holds_together_names_that_city() -> None:
    """Both triangles reach each other only through ``waist``, and nothing else is named."""
    assert cut_cities(_BOWTIE) == ["waist"]


def test_a_network_two_cities_hold_together_names_both_of_them() -> None:
    """A chain of four is split by either of its middle cities, and by neither of its ends.

    Two findings from one network, which is what says the reading reports every city it
    finds rather than stopping at the first one.
    """
    assert cut_cities(_CHAIN) == ["centre", "middle"]


def test_a_network_that_is_already_in_pieces_names_nobody() -> None:
    """A city cannot split what is split already, so two separate paths name no city.

    Reported as no finding rather than as every city, because a list naming all six cities
    of a two-piece network answers a question nobody asked and hides the one finding that
    matters -- which ``backbone_groups`` makes.
    """
    assert cut_cities(_APART) == []
