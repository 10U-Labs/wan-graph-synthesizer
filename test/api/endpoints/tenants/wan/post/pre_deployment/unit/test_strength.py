"""Unit tests for PoP strength scoring, and the compass sectors it counts."""

from __future__ import annotations

import math

import pytest

import fixtures
from synthesizer.input_graph import Vertex
from synthesizer.strength import link_bearing, link_octants

_ORIGIN = "origin"


def _at_bearing(bearing: float) -> Vertex:
    """A PoP one degree from the origin, in the given compass direction."""
    radians = math.radians(bearing)
    return fixtures.carrier_pop(
        f"n{int(bearing)}", math.cos(radians), math.sin(radians)
    )


def _sectors(compass_octants: int, *bearings: float) -> set[int]:
    """The sectors the origin's links fall in, with the compass cut that many ways."""
    neighbors = [_at_bearing(bearing) for bearing in bearings]
    pop_by_id = {_ORIGIN: fixtures.carrier_pop(_ORIGIN)}
    pop_by_id.update({neighbor.id: neighbor for neighbor in neighbors})
    adjacency = {_ORIGIN: [(neighbor.id, 1.0) for neighbor in neighbors]}
    return link_octants(_ORIGIN, adjacency, pop_by_id, compass_octants)


def test_a_due_north_link_bears_zero() -> None:
    """The fixture places a zero-degree neighbour due north of the origin."""
    assert round(link_bearing(fixtures.carrier_pop(_ORIGIN), _at_bearing(0.0))) == 0


def test_eight_sectors_keep_the_octant_boundaries() -> None:
    """At eight, north, north-east and east land in three adjacent sectors."""
    assert _sectors(8, 0.0, 45.0, 90.0) == {0, 1, 2}


def test_eight_sectors_separate_links_forty_degrees_apart() -> None:
    """At eight, two links forty degrees apart fall in different sectors."""
    assert len(_sectors(8, 0.0, 40.0)) == 2


def test_four_sectors_merge_links_forty_degrees_apart() -> None:
    """At four, the same two links share one ninety-degree sector."""
    assert len(_sectors(4, 0.0, 40.0)) == 1


def test_one_sector_holds_every_direction() -> None:
    """At one, the compass is a single sector and every link is in it."""
    assert _sectors(1, 0.0, 40.0, 130.0, 250.0, 350.0) == {0}


@pytest.mark.parametrize("compass_octants", [1, 2, 3, 4, 6, 8, 12, 16])
def test_the_direction_term_stays_within_one(compass_octants: int) -> None:
    """However the compass is cut, the sectors reached never outnumber the sectors."""
    reached = _sectors(compass_octants, 0.0, 40.0, 90.0, 137.0, 200.0, 265.0, 310.0, 350.0)
    assert len(reached) <= compass_octants
