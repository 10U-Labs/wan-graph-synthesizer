"""Integration test: how many fiber miles a whole synthesis orders, and how few it could have.

A design grows by paths that are each defensible on their own. That is how 54 of the 192
published paths came to buy nobody a way out, 23,917 miles of fiber six tenants pay for
every month and get nothing for (GitHub issue #60): every one of them was the shortest way
to join the pair it joined, or the shortest way round a city carrying the network, and no
assertion anywhere asked what the design cost in total. A total is the only assertion that
notices that, so this file makes one, over a graph whose answer can be worked out by hand.

The graph is four sites on a ring of hundred-mile segments with the two chords priced at two
hundred and fifty. Every site is bought two ways out and has three fiber directions to find
them in, so the ring is the answer and the chords are what make it an answer rather than the
only design there is. Four sites needing two ways out apiece come to eight ends, and a
segment carries two, so no design holds fewer than four segments; the four shortest are the
ring, at four hundred miles.

The ring cannot reach every way this goes wrong, because its answer is settled by the first
solve the search runs. ``synthesizer.survivable`` writes its requirements down as an answer
violates them, and a limit of 24 passes on that used to stand in the module: on a graph
answered in one pass a limit of any size is invisible, and on the six real maps, which need
between 645 and 1,382 passes, it stopped every search early and bought fiber on an answer
that still missed requirements (GitHub issue #63). So a second graph runs here, twelve cities
of carrier fiber with five backbone seats, whose search takes 26 passes. Left to finish it
delivers the 159 miles of its own floor; stopped at 24 it delivered 176.

The second assertion is the guarantee the fiber choice carries, stated rather than assumed.
``synthesizer.survivable`` chooses the fiber by iterative rounding of a linear-programming
relaxation, and publishes that relaxation's own answer as the floor under the whole problem
-- no design meeting the same requirements runs fewer miles than that. The design it
produces is at most twice the floor. An implementation that has lost the guarantee through a
defect fails here, which is a thing an approximation cannot otherwise report about itself.
"""

from __future__ import annotations

import pytest

import fixtures

_SITES = ("w", "x", "y", "z")
_ASKED_FOR = 2
# The ring and its two chords. A chord is the shortest way between the two sites it joins,
# which is exactly what a pass drawing one pair at a time would reach for, and it buys
# neither of them a way out the ring has not already given them.
_SEGMENTS = {
    ("w", "x"): 100.0, ("x", "y"): 100.0, ("y", "z"): 100.0, ("z", "w"): 100.0,
    ("w", "y"): 250.0, ("x", "z"): 250.0,
}
ARTIFACTS = fixtures.design_over_segments(_SITES, _SEGMENTS, _ASKED_FOR)
_MESH = fixtures.mesh_paths(ARTIFACTS)


def test_the_delivered_design_orders_the_four_hundred_miles_the_ring_costs() -> None:
    """Four hundred miles of fiber, which is the fewest four sites owed two ways out can hold.

    Pinned rather than bounded, because a total is what notices a design growing by paths
    that are each defensible on their own. Any change that inflates this design has to
    account for itself here.
    """
    assert ARTIFACTS.design.metrics.physical_miles == 400.0


def test_the_delivered_design_draws_one_path_a_pair_round_the_ring() -> None:
    """Four paths, one for each pair of neighbours, and neither chord drawn."""
    assert sum(use.distance_miles for use in _MESH) == 400.0


def test_the_delivered_design_publishes_the_floor_it_is_judged_against() -> None:
    """The fewest miles any design meeting the same requirements could run is four hundred.

    Published with the design because a claim that a network is close to the shortest one
    there is means nothing until the shortest one there is has a number an operator can
    read.
    """
    assert round(ARTIFACTS.design.metrics.backbone_lower_bound_miles, 3) == 400.0


def test_the_delivered_design_runs_no_further_than_twice_that_floor() -> None:
    """The guarantee the fiber choice carries, asserted against a design the pipeline built."""
    assert (
        ARTIFACTS.design.metrics.physical_miles
        <= 2 * ARTIFACTS.design.metrics.backbone_lower_bound_miles
    )


def test_every_site_still_holds_the_two_ways_out_it_was_bought() -> None:
    """Four hundred miles is only a saving if it costs no site a way out, and it costs none."""
    assert ARTIFACTS.validation["backbone_mesh_independence_deficient"] == []


# Twelve cities of carrier fiber, five of them backbone seats and seven of them cities the
# fiber crosses. Unlike the ring above, this graph's search needs 26 passes to settle, which
# is what makes it the one fixture here that notices a search stopping early.
MANY_PASS_ARTIFACTS = fixtures.design_over_segments(
    fixtures.MANY_PASS_SITES,
    fixtures.MANY_PASS_SEGMENTS,
    _ASKED_FOR,
    transit_ids=fixtures.MANY_PASS_TRANSIT,
)


def test_a_design_whose_search_takes_many_passes_orders_the_fewest_miles_there_are() -> None:
    """159 miles delivered over a graph that needs 26 passes to work out what to buy.

    Pinned, because the number is what moves when the search stops early: cut off at 24
    passes this same graph delivered 176 miles, fiber the operator holds and pays for every
    month having bought nothing with it.
    """
    assert MANY_PASS_ARTIFACTS.design.metrics.physical_miles == fixtures.MANY_PASS_MILES


def test_that_design_orders_exactly_the_floor_it_publishes_rather_than_twice_it() -> None:
    """The design and the fewest miles any design meeting its requirements could run agree.

    Asserted as an equality rather than as the factor of two the method guarantees, because
    a factor of two is too loose to catch this: cut off at 24 passes the same graph delivered
    176 miles against a floor of 159, which is 1.107 times it and comfortably inside the
    guarantee. The six real maps are where the factor of two does bite -- Two-Node published
    2.078 times its floor -- and no graph small enough to run in this tier reproduces that.
    Landing on the floor exactly says something stronger than being near it: there is no
    shorter design.
    """
    assert MANY_PASS_ARTIFACTS.design.metrics.physical_miles == pytest.approx(
        MANY_PASS_ARTIFACTS.design.metrics.backbone_lower_bound_miles
    )


def test_every_seat_on_that_design_holds_the_two_ways_out_it_was_bought() -> None:
    """Fewer miles is only a saving if it costs no site a way out, and it costs none here.

    The cheapest way to run few miles is to buy fiber that leaves a site short, so the
    mileage above means nothing without this beside it.
    """
    assert MANY_PASS_ARTIFACTS.validation["backbone_mesh_independence_deficient"] == []
