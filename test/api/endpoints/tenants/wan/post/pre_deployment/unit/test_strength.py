from __future__ import annotations

import math

import pytest

import fixtures
from synthesizer.input_graph import Site
from synthesizer.strength import (
    backbone_strength,
    diverse_path_bounds,
    link_bearing,
    link_sectors,
)

_ORIGIN = "origin"


def _at_bearing(bearing: float) -> Site:
    radians = math.radians(bearing)
    return fixtures.carrier_pop(
        f"n{int(bearing)}", math.cos(radians), math.sin(radians)
    )


def _sectors(compass_sector_count: int, *bearings: float) -> set[int]:
    neighbors = [_at_bearing(bearing) for bearing in bearings]
    pop_by_id = {_ORIGIN: fixtures.carrier_pop(_ORIGIN)}
    pop_by_id.update({neighbor.id: neighbor for neighbor in neighbors})
    adjacency = {_ORIGIN: [(neighbor.id, 1.0) for neighbor in neighbors]}
    return link_sectors(_ORIGIN, adjacency, pop_by_id, compass_sector_count)


def test_a_due_north_link_bears_zero() -> None:
    assert round(link_bearing(fixtures.carrier_pop(_ORIGIN), _at_bearing(0.0))) == 0


def test_eight_sectors_keep_the_octant_boundaries() -> None:
    assert _sectors(8, 0.0, 45.0, 90.0) == {0, 1, 2}


def test_eight_sectors_separate_links_forty_degrees_apart() -> None:
    assert len(_sectors(8, 0.0, 40.0)) == 2


def test_four_sectors_merge_links_forty_degrees_apart() -> None:
    assert len(_sectors(4, 0.0, 40.0)) == 1


def test_one_sector_holds_every_direction() -> None:
    assert _sectors(1, 0.0, 40.0, 130.0, 250.0, 350.0) == {0}


@pytest.mark.parametrize("compass_sector_count", [1, 2, 3, 4, 6, 8, 12, 16])
def test_the_direction_term_stays_within_one(compass_sector_count: int) -> None:
    reached = _sectors(compass_sector_count, 0.0, 40.0, 90.0, 137.0, 200.0, 265.0, 310.0, 350.0)
    assert len(reached) <= compass_sector_count


_FUNNEL_INPUTS = fixtures.funnel_inputs()
_FUNNEL_BOUNDS = diverse_path_bounds(set(fixtures.FUNNEL_ELIGIBLE), _FUNNEL_INPUTS.adjacency)


def _funnel_strength(site: str) -> float:
    pop_by_id = {pop.id: pop for pop in _FUNNEL_INPUTS.carrier_pops}
    return backbone_strength(site, _FUNNEL_INPUTS, pop_by_id, _FUNNEL_BOUNDS, 8)


def test_the_funnelled_site_has_the_most_fiber_segments() -> None:
    segments = {site: len(_FUNNEL_INPUTS.adjacency[site]) for site in ("funnel", "spread")}
    assert (segments["funnel"], segments["spread"]) == (5, 3)


def test_the_funnelled_site_is_held_to_its_two_failure_points() -> None:
    assert _FUNNEL_BOUNDS.per_site["funnel"] == 2


def test_the_bound_ranks_the_spread_site_above_the_funnelled_one() -> None:
    assert _FUNNEL_BOUNDS.per_site["spread"] > _FUNNEL_BOUNDS.per_site["funnel"]


def test_strength_ranks_the_spread_site_above_the_funnelled_one() -> None:
    assert _funnel_strength("spread") > _funnel_strength("funnel")


def test_a_site_with_no_fiber_cannot_divide_the_score_by_zero() -> None:
    assert diverse_path_bounds({"lonely"}, {}).largest == 1
