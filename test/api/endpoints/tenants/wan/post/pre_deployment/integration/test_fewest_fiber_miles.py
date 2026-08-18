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

The second assertion is the guarantee the fiber choice carries, stated rather than assumed.
``synthesizer.survivable`` chooses the fiber by iterative rounding of a linear-programming
relaxation, and publishes that relaxation's own answer as the floor under the whole problem
-- no design meeting the same requirements runs fewer miles than that. The design it
produces is at most twice the floor. An implementation that has lost the guarantee through a
defect fails here, which is a thing an approximation cannot otherwise report about itself.
"""

from __future__ import annotations

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
