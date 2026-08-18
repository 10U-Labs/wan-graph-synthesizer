"""Unit tests for PoP strength scoring, and the compass sectors it counts."""

from __future__ import annotations

import math

import pytest

import fixtures
from synthesizer.input_graph import Vertex
from synthesizer.strength import (
    backbone_strength,
    diverse_path_bounds,
    link_bearing,
    link_sectors,
)

_ORIGIN = "origin"


def _at_bearing(bearing: float) -> Vertex:
    """A PoP one degree from the origin, in the given compass direction."""
    radians = math.radians(bearing)
    return fixtures.carrier_pop(
        f"n{int(bearing)}", math.cos(radians), math.sin(radians)
    )


def _sectors(compass_sector_count: int, *bearings: float) -> set[int]:
    """The sectors the origin's links fall in, with the compass cut that many ways."""
    neighbors = [_at_bearing(bearing) for bearing in bearings]
    pop_by_id = {_ORIGIN: fixtures.carrier_pop(_ORIGIN)}
    pop_by_id.update({neighbor.id: neighbor for neighbor in neighbors})
    adjacency = {_ORIGIN: [(neighbor.id, 1.0) for neighbor in neighbors]}
    return link_sectors(_ORIGIN, adjacency, pop_by_id, compass_sector_count)


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


@pytest.mark.parametrize("compass_sector_count", [1, 2, 3, 4, 6, 8, 12, 16])
def test_the_direction_term_stays_within_one(compass_sector_count: int) -> None:
    """However the compass is cut, the sectors reached never outnumber the sectors."""
    reached = _sectors(compass_sector_count, 0.0, 40.0, 90.0, 137.0, 200.0, 265.0, 310.0, 350.0)
    assert len(reached) <= compass_sector_count


# The protection term counts diverse paths rather than fiber segments, so the tests below run
# over the one fixture graph where the two measures disagree (see ``fixtures.FUNNEL_EDGES``).
_FUNNEL_INPUTS = fixtures.funnel_inputs()
_FUNNEL_BOUNDS = diverse_path_bounds(set(fixtures.FUNNEL_ELIGIBLE), _FUNNEL_INPUTS.adjacency)


def _funnel_strength(site: str) -> float:
    """One site's strength over the disagreement graph, at the default compass cut."""
    pop_by_id = {pop.id: pop for pop in _FUNNEL_INPUTS.carrier_pops}
    return backbone_strength(site, _FUNNEL_INPUTS, pop_by_id, _FUNNEL_BOUNDS, 8)


def test_the_funnelled_site_has_the_most_fiber_segments() -> None:
    """The fixture's premise: the funnel has five segments where the spread site has three."""
    segments = {site: len(_FUNNEL_INPUTS.adjacency[site]) for site in ("funnel", "spread")}
    assert (segments["funnel"], segments["spread"]) == (5, 3)


def test_the_funnelled_site_is_held_to_its_two_failure_points() -> None:
    """Five segments converging on two upstream cities carry two diverse paths, not five."""
    assert _FUNNEL_BOUNDS.per_site["funnel"] == 2


def test_the_bound_ranks_the_spread_site_above_the_funnelled_one() -> None:
    """With fewer segments and three separate ways out, the spread site carries more."""
    assert _FUNNEL_BOUNDS.per_site["spread"] > _FUNNEL_BOUNDS.per_site["funnel"]


def test_strength_ranks_the_spread_site_above_the_funnelled_one() -> None:
    """The score follows the fiber's protection, not the number of segments touching a site.

    This is the ranking the segment-count term got backwards: it scored the funnel a full 1.0
    against the spread site's 0.6 and put the weaker site first.
    """
    assert _funnel_strength("spread") > _funnel_strength("funnel")


def test_a_site_with_no_fiber_cannot_divide_the_score_by_zero() -> None:
    """Fiber carrying no segments at all leaves the largest bound at one rather than nothing."""
    assert diverse_path_bounds({"lonely"}, {}).largest == 1
