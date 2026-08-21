"""Integration test: how many fiber miles a whole synthesis orders, and how few it could have.

A synthesis grows by paths that are each defensible on their own. That is how 54 of the 192
published paths came to buy nobody a way out, 23,917 miles of fiber six tenants were paying
for then and got nothing for (GitHub issue #60): every one of them was the shortest way
to join the pair it joined, or the shortest way round a city carrying the network, and no
assertion anywhere asked what the synthesis cost in total. A total is the only assertion that
notices that, so this file makes one, over a graph whose answer can be worked out by hand.

The graph is four sites on a ring of hundred-mile segments with the two chords priced at two
hundred and fifty. Every site is bought two ways out and has three fiber directions to find
them in, so the ring is the answer and the chords are what make it an answer rather than the
only synthesis there is. Four sites needing two ways out apiece come to eight ends, and a
segment carries two, so no synthesis holds fewer than four segments; the four shortest are the
ring, at four hundred miles.

The ring cannot reach every way this goes wrong, because its answer is settled by the first
solve the search runs. ``synthesizer.survivable`` writes its requirements down as an answer
violates them, and a limit of 24 passes on that used to stand in the module: on a graph
answered in one pass a limit of any size is invisible, and on the six real maps there were
then, which needed between 645 and 1,382 passes, it stopped every search early and bought
fiber on an answer that still missed requirements (GitHub issue #63). So a second graph runs
here, twelve cities of carrier fiber with five backbone seats, whose search takes 26 passes.
Left to finish it delivers the 159 miles of its own floor; stopped at 24 it delivered 176.

The second assertion is the guarantee the fiber choice carries, stated rather than assumed.
``synthesizer.survivable`` chooses the fiber by iterative rounding of a linear-programming
relaxation, and publishes that relaxation's own answer as the floor under the whole problem
-- no synthesis meeting the same requirements runs fewer miles than that. The synthesis it
produces is at most twice the floor. An implementation that has lost the guarantee through a
defect fails here, which is a thing an approximation cannot otherwise report about itself.

A third graph carries the owners. Neither of the two above says who has fiber where, and a
segment naming no carrier is one every carrier's path may run over, so on both of them what
a site can be sold and what its fiber alone could carry are the same number by construction.
The third is a ring of four cities, two of them seats, whose way round through ``q`` is half
Zayo's and half Lumen's -- a way round nobody quotes, since a path is ordered from one
carrier end to end. Each seat therefore holds one way out and not the two the ring's shape
suggests, and a floor priced for two would sit above the fiber the synthesis actually
orders. That is what Yurop published: 8,844.892 miles ordered against a floor of 9,141.641
it had already beaten, because Boston, MA was priced for a second way out no carrier sells
(GitHub issue #111).

"""

from __future__ import annotations

import pytest

import fixtures
from synthesizer import linear_program
from synthesizer.model import SynthesisArtifacts

_SITES = ("w", "x", "y", "z")
_ASKED_FOR = 2
# The ring and its two chords. A chord is the shortest way between the two sites it joins,
# which is exactly what a pass drawing one pair at a time would reach for, and it buys
# neither of them a way out the ring has not already given them.
_SEGMENTS = {
    ("w", "x"): 100.0, ("x", "y"): 100.0, ("y", "z"): 100.0, ("z", "w"): 100.0,
    ("w", "y"): 250.0, ("x", "z"): 250.0,
}
ARTIFACTS = fixtures.synthesis_over_segments(_SITES, _SEGMENTS, _ASKED_FOR)
_MESH = fixtures.mesh_paths(ARTIFACTS)


def test_the_delivered_synthesis_orders_the_four_hundred_miles_the_ring_costs() -> None:
    """Four hundred miles of fiber, which is the fewest four sites owed two ways out can hold.

    Pinned rather than bounded, because a total is what notices a synthesis growing by paths
    that are each defensible on their own. Any change that inflates this synthesis has to
    account for itself here.
    """
    assert ARTIFACTS.synthesis.metrics.physical_miles == 400.0


def test_the_delivered_synthesis_draws_one_path_a_pair_round_the_ring() -> None:
    """Four paths, one for each pair of neighbours, and neither chord drawn."""
    assert sum(use.distance_miles for use in _MESH) == 400.0


def test_the_delivered_synthesis_publishes_the_floor_it_is_judged_against() -> None:
    """The fewest miles any synthesis meeting the same requirements could run is four hundred.

    Published with the synthesis because a claim that a network is close to the shortest one
    there is means nothing until the shortest one there is has a number an operator can
    read.
    """
    assert round(ARTIFACTS.synthesis.metrics.backbone_lower_bound_miles, 3) == 400.0


def test_the_delivered_synthesis_runs_no_further_than_twice_that_floor() -> None:
    """The guarantee the fiber choice carries, asserted against a synthesis the pipeline built."""
    assert (
        ARTIFACTS.synthesis.metrics.physical_miles
        <= 2 * ARTIFACTS.synthesis.metrics.backbone_lower_bound_miles
    )


def test_every_site_still_holds_the_two_ways_out_it_was_bought() -> None:
    """Four hundred miles is only a saving if it costs no site a way out, and it costs none."""
    assert ARTIFACTS.validation["backbone_mesh_independence_deficient"] == []


def _many_pass_artifacts() -> SynthesisArtifacts:
    """Twelve cities of carrier fiber with five backbone seats, synthesized end to end.

    Seven of the twelve are cities the fiber crosses rather than seats. Unlike the ring
    above, this graph's search needs 26 passes to settle, which is what makes it the one
    fixture here that notices a search stopping early. Written as a function because two
    tests need it built under different conditions, not because it changes between them.
    """
    return fixtures.synthesis_over_segments(
        fixtures.MANY_PASS_SITES,
        fixtures.MANY_PASS_SEGMENTS,
        _ASKED_FOR,
        transit_ids=fixtures.MANY_PASS_TRANSIT,
    )


MANY_PASS_ARTIFACTS = _many_pass_artifacts()


def test_a_synthesis_whose_search_takes_many_passes_orders_the_fewest_miles_there_are() -> None:
    """159 miles delivered over a graph that needs 26 passes to work out what to buy.

    Pinned, because the number is what moves when the search stops early: cut off at 24
    passes this same graph delivered 176 miles, fiber the operator holds and pays for every
    month having bought nothing with it.
    """
    assert MANY_PASS_ARTIFACTS.synthesis.metrics.physical_miles == fixtures.MANY_PASS_MILES


def test_that_synthesis_orders_exactly_the_floor_it_publishes_rather_than_twice_it() -> None:
    """The synthesis and the fewest miles any synthesis meeting its requirements could run agree.

    Asserted as an equality rather than as the factor of two the method guarantees, because
    a factor of two is too loose to catch this: cut off at 24 passes the same graph delivered
    176 miles against a floor of 159, which is 1.107 times it and comfortably inside the
    guarantee. The five real maps are where the factor of two does bite -- Two-Node published
    2.078 times its floor -- and no graph small enough to run in this tier reproduces that.
    Landing on the floor exactly says something stronger than being near it: there is no
    shorter synthesis.
    """
    assert MANY_PASS_ARTIFACTS.synthesis.metrics.physical_miles == pytest.approx(
        MANY_PASS_ARTIFACTS.synthesis.metrics.backbone_lower_bound_miles
    )


def test_every_seat_on_that_synthesis_holds_the_two_ways_out_it_was_bought() -> None:
    """Fewer miles is only a saving if it costs no site a way out, and it costs none here.

    The cheapest way to run few miles is to buy fiber that leaves a site short, so the
    mileage above means nothing without this beside it.
    """
    assert MANY_PASS_ARTIFACTS.validation["backbone_mesh_independence_deficient"] == []


def test_that_synthesis_is_the_same_synthesis_when_every_pass_of_its_search_gives_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """159 miles again, over a search in which no pass answers before it runs out of time.

    A pass that runs out of time is asked again with the basis it carried thrown away, and
    what the whole synthesis delivers has to be what it delivers without that having
    happened. Forced here on every one of the 26 passes rather than on one of them, since
    the retry is only ever reached on a national map -- DOW takes it once in 4,478 passes,
    and no graph small enough to run in this tier reaches it at all (GitHub issue #70).
    """
    monkeypatch.setattr(linear_program, "_SECONDS_A_PASS_MAY_RUN", 0.0)
    assert _many_pass_artifacts().synthesis.metrics.physical_miles == fixtures.MANY_PASS_MILES


# A ring of four cities with two seats, and the owners written on the fiber. Lumen has the
# way round through ``p`` whole; the way round through ``q`` is Zayo's on the way out of
# ``w`` and Lumen's on the way in to ``x``, so nobody can quote it. Each seat holds one way
# out and not the two the ring's shape offers, and the way nobody sells is priced at three
# hundred against the two hundred of the way somebody does, so the shorter way is also the
# sellable one and the answer is forced whole.
_SPLIT_SITES = ("w", "x")
_SPLIT_TRANSIT = ("p", "q")
_SPLIT_SEGMENTS = {
    ("w", "p"): (100.0, ("lumen",)),
    ("p", "x"): (100.0, ("lumen",)),
    ("w", "q"): (150.0, ("zayo",)),
    ("q", "x"): (150.0, ("lumen",)),
}
SPLIT_ARTIFACTS = fixtures.synthesis_over_owned_fiber(
    _SPLIT_SITES, _SPLIT_SEGMENTS, _ASKED_FOR, _SPLIT_TRANSIT
)
SPLIT_ASKED_ONE_ARTIFACTS = fixtures.synthesis_over_owned_fiber(
    _SPLIT_SITES, _SPLIT_SEGMENTS, 1, _SPLIT_TRANSIT
)
# Five millimetres, so an equality between two mileages is not decided by the last bit of a
# float coming back from a solved program.
_SLACK = 1e-6


def test_no_synthesis_runs_fewer_miles_than_the_floor_it_publishes() -> None:
    """The split ring orders at least the miles it says no synthesis can go below.

    A synthesis under its own floor is arithmetic that has come apart, and until this graph
    arrived no fixture in this tier could produce it: the floor is measured over the
    requirements the search wrote down, and on fiber naming no owner those requirements are
    exactly what the shape allows. Here they are not, and a floor still priced for the way
    round nobody sells would come out at five hundred miles over a synthesis that correctly
    orders two hundred.
    """
    assert SPLIT_ARTIFACTS.synthesis.metrics.physical_miles >= (
        SPLIT_ARTIFACTS.synthesis.metrics.backbone_lower_bound_miles - _SLACK
    )


def test_a_site_whose_ways_out_are_split_between_carriers_is_floored_at_what_it_can_buy(
) -> None:
    """Two ways out asked for over this ring is floored where one way out is: two hundred miles.

    The tightening stated as a number rather than as an inequality. Both seats can be sold
    one way out and no more, so a tenant asking for two is answered at one and the floor is
    the two hundred miles of the way round through ``p`` -- the same number this fiber is
    floored at when the tenant asks for one outright, which is the requirement written down
    by hand at what a carrier can sell.
    """
    assert SPLIT_ARTIFACTS.synthesis.metrics.backbone_lower_bound_miles == pytest.approx(
        SPLIT_ASKED_ONE_ARTIFACTS.synthesis.metrics.backbone_lower_bound_miles
    )
