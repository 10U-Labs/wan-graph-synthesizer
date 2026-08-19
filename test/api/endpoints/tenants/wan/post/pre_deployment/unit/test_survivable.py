"""Unit tests for choosing the fiber a whole backbone is built from in one decision.

What this module settles is which of the carrier's fiber segments a tenant's synthesis stands
on, so every graph here is shaped to force one answer rather than to leave two syntheses of
equal mileage for a solver to pick between. A four-site ring is the clearest of them: every
site is owed two ways out, each site has exactly two segments, and the only synthesis meeting
that is the whole ring, whose mileage is the ring's own. The rest are that ring with one
part changed -- a long chord nothing needs, a chain that leaves a site behind one city, two
triangles held apart by a single segment, a pair with two ways round it -- so that each
test turns on one part of the choice and the fixture beside it says which.

One graph here is not shaped by hand, and it is the last. The choice is made by writing a
requirement down as an answer violates it and solving again, and every graph above settles
in a pass or two, so none of them can tell a search that finished from one that was cut off
part-way. Twelve cities of carrier fiber with five backbone seats takes 26 passes, which is
what makes it the fixture that notices (GitHub issue #63).

The floor published with the choice is asserted as a number only where the graph forces the
number, and as an inequality over every fixture at the end. No synthesis meeting the same
requirements can run fewer miles than the floor, and a floor above the fiber actually bought
would be a claim the synthesis cannot be as short as it already is.
"""

from __future__ import annotations

import pytest

import fixtures
from synthesizer.ceiling import BackupPathLimit
from synthesizer.graphs import build_adjacency, distances_from
from synthesizer.input_graph import PhysicalEdge
from synthesizer.survivable import (
    FiberChoice,
    FiberInputs,
    _held,
    _requirements,
    _shortfalls,
    admissible_fiber,
    choose_fiber,
)

physical = fixtures.physical_edges_from

# What every tenant in etc/*.yml asks for: two ways out of each backbone node that no one
# city's loss takes together.
_WAYS_OUT = 2
# Five millimetres, the slack the module itself allows for the arithmetic of a solved
# program, so an equality between two mileages is not decided by the last bit of a float.
_SLACK = 1e-6


def _all_distances(
    edges: dict[tuple[str, str], PhysicalEdge]
) -> dict[str, dict[str, float]]:
    """The shortest way over this fiber from every city on it to every other."""
    cities = sorted({city for pair in edges for city in pair})
    return distances_from(build_adjacency(edges), cities)


def _chosen(
    edges: dict[tuple[str, str], PhysicalEdge],
    backbone_ids: tuple[str, ...],
    per_peer: int = 1,
) -> FiberChoice:
    """The fiber a backbone of these sites is built from, with no bound on a path's length."""
    return choose_fiber(
        FiberInputs(backbone_ids, edges, _all_distances(edges), _WAYS_OUT, per_peer)
    )


def _bought_miles(
    choice: FiberChoice, edges: dict[tuple[str, str], PhysicalEdge]
) -> float:
    """How many fiber miles the segments a choice bought actually run."""
    return sum(edges[segment].distance_miles for segment in choice.segments)


# The three-site crossing graph from the shared fixtures: twenty miles apart overland
# through ``pdx``, a thousand miles apart offshore through ``tok``. It is the one fixture
# whose segments differ by orders of magnitude, which is what a backup path multiple is
# measured against, and the overland fiber is what is left when the crossing is refused.
_CROSSING_SITES = ("eug", "hil", "sea")
_CROSSING_DISTANCES = _all_distances(fixtures.CROSSING_EDGES)
_OVERLAND = frozenset({("eug", "pdx"), ("hil", "pdx"), ("pdx", "sea")})
_EVERY_CROSSING_SEGMENT = frozenset(fixtures.CROSSING_EDGES)


def _admissible(multiple: float | None) -> frozenset[tuple[str, str]]:
    """The crossing graph's fiber a path inside this backup path multiple could run over."""
    limit = None if multiple is None else BackupPathLimit(multiple, _CROSSING_DISTANCES)
    return frozenset(admissible_fiber(FiberInputs(
        _CROSSING_SITES, fixtures.CROSSING_EDGES, _CROSSING_DISTANCES, _WAYS_OUT, 1, limit
    )))


def test_with_no_bound_in_hand_every_segment_the_carrier_has_is_admissible() -> None:
    """No backup path multiple means no fiber to rule out, so all six segments stand.

    It is the behaviour every caller with no tenant to be measured against relies on, and
    the case the two below are read against.
    """
    assert _admissible(None) == _EVERY_CROSSING_SEGMENT


def test_fiber_no_admissible_path_could_run_over_is_left_out_of_the_choice() -> None:
    """At a multiple of three the crossing goes and the overland fiber stays.

    Two thousand miles of ocean to cover the twenty ``sea`` sits from either peer is a
    hundred times the direct distance, so no path a tenant allows runs over it. Leaving it
    in the choice is what would let the program buy an ocean crossing to protect a state
    line (GitHub issue #44).
    """
    assert _admissible(3.0) == _OVERLAND


def test_a_multiple_wide_enough_for_the_crossing_keeps_the_crossing() -> None:
    """At a multiple of a thousand the ocean is inside what the tenant allows, so it stays.

    The bound refuses a detour rather than an ocean, and which it is doing is the tenant's
    number and nothing else.
    """
    assert _admissible(1000.0) == _EVERY_CROSSING_SEGMENT


# A backbone the carrier's fiber says nothing about, and a backbone with no sites to serve.
# Both end with nothing bought, and they arrive there differently: the first has no fiber to
# choose from and never reaches the solver, the second has fiber and nothing asked of it.
_NO_FIBER = _chosen(physical({}), ("a", "b"))
_NO_SITES = _chosen(physical({("a", "b"): 1.0}), ())


def test_a_backbone_with_no_fiber_at_all_buys_nothing_and_is_floored_at_nothing() -> None:
    """No fiber to choose from, so the choice is empty and the floor under it is zero.

    The shortfall belongs to the report rather than to a program with no columns, and
    ``synthesizer.validation.backbone_mesh_independence_deficient`` is what names it.
    """
    assert _NO_FIBER == FiberChoice(frozenset(), 0.0)


def test_a_backbone_with_no_sites_buys_none_of_the_fiber_in_front_of_it() -> None:
    """Fiber on offer and nobody to serve, so nothing is required and nothing is bought."""
    assert not _NO_SITES.segments


def test_a_backbone_with_no_sites_is_floored_at_nothing_rather_than_at_what_is_on_offer() -> None:
    """The floor is what the requirements cost, and no site here asks for anything.

    It still comes back, computed over a program carrying every requirement written down --
    here none of them -- so it is zero miles rather than the mileage the map offers.
    """
    assert _NO_SITES.lower_bound_miles == pytest.approx(0.0)


# A four-site ring, one mile a segment. Each site has two segments and is owed two ways out,
# so every segment is on the only synthesis that meets the requirement and the answer is forced
# whole. The same ring with a ten-mile chord across it is the fixture beside it: the chord
# buys nobody a way out the ring has not already bought, so a choice that is a choice leaves
# it, and a choice that simply takes the fiber it was offered does not.
_RING_PAIRS = {("a", "b"): 1.0, ("b", "c"): 1.0, ("c", "d"): 1.0, ("a", "d"): 1.0}
_RING_SITES = ("a", "b", "c", "d")
_RING_SEGMENTS = frozenset(_RING_PAIRS)
_RING = physical(_RING_PAIRS)
_CHORD = physical({**_RING_PAIRS, ("a", "c"): 10.0})
_RING_CHOICE = _chosen(_RING, _RING_SITES)
_CHORD_CHOICE = _chosen(_CHORD, _RING_SITES)


def test_a_ring_is_bought_whole_because_nothing_short_of_it_gives_two_ways_out() -> None:
    """Four sites owed two ways out each over four segments, so all four are bought.

    Withdraw any one segment and the two sites it joined hold one way out apiece, which is
    less than the tenant asked for. The synthesis is the ring because there is no other.
    """
    assert _RING_CHOICE.segments == _RING_SEGMENTS


def test_the_floor_under_the_ring_is_the_mileage_of_the_ring_itself() -> None:
    """Four one-mile segments and no synthesis meeting the requirement without all four.

    The floor is the number a finished synthesis is published against, so a floor under four
    here would let a synthesis run longer than it should and still read as close to ideal.
    """
    assert _RING_CHOICE.lower_bound_miles == pytest.approx(4.0)


def test_fiber_no_requirement_turns_on_is_left_where_it_is() -> None:
    """The ring is bought and the ten-mile chord across it is not, so the choice is a choice.

    Every site already holds its two ways out over the ring, so the chord buys nobody
    anything and an operator holding it would pay for it every month for nothing. This is
    the shape of the 54 published paths GitHub issue #60 counted, asked of the fiber rather
    than of the paths read off it.
    """
    assert _CHORD_CHOICE.segments == _RING_SEGMENTS


# A chain of three sites: ``b`` in the middle with a way out either side, and ``a`` and ``c``
# each behind it. No amount of buying gives ``a`` a second way out on this fiber, so the two
# it was asked for has to come down to the one the carrier can carry.
_CHAIN = physical({("a", "b"): 1.0, ("b", "c"): 1.0})
_CHAIN_CHOICE = _chosen(_CHAIN, ("a", "b", "c"))


def test_a_site_behind_a_single_point_of_failure_is_asked_for_what_its_fiber_can_carry() -> None:
    """The chain is bought whole, which is only possible because ``a`` was asked for one way out.

    Left at the two its tenant asked for, the row for ``a`` would ask for two units over the
    single segment it stands on, which holds one, and the program would have no answer at
    all -- a build that fails rather than a synthesis with an honest shortfall in it. The
    shortfall is then reported by
    ``synthesizer.validation.backbone_mesh_independence_deficient``.
    """
    assert _CHAIN_CHOICE.segments == frozenset(_CHAIN)


# Two sites and two ways round between them, through ``p`` and through ``q``. This is the
# backbone :func:`synthesizer.ceiling.paths_per_peer` returns a number above one for: a
# tenant asking for two ways out where there is only one peer to reach, so the peer stops
# being a city a way out is charged for and becomes a destination both may share.
_TWIN_WAYS = physical({
    ("a", "p"): 1.0, ("b", "p"): 1.0, ("a", "q"): 1.0, ("b", "q"): 1.0,
})
_TWIN_CHOICE = _chosen(_TWIN_WAYS, ("a", "b"), per_peer=2)


def test_a_pair_allowed_two_ways_between_them_is_given_both_ways_round() -> None:
    """One peer to reach and two ways out asked for, so both ways round the pair are bought.

    With one way out per peer the fiber through ``p`` would answer the whole requirement and
    ``q`` would be left where it is, which is the synthesis Two-Node would have been given: a
    backbone of Ashburn, VA and Salt Lake City, UT joined once and asked for twice (GitHub
    issue #58).
    """
    assert _TWIN_CHOICE.segments == frozenset(_TWIN_WAYS)


# Two triangles joined by the one segment between ``c`` and ``d``. Each site has two segments
# of its own triangle, so the fewest miles meeting every site's own requirement is the six
# triangle segments and that seventh segment is left at nothing -- and that answer separates
# ``a`` from ``d`` entirely. It is the fixture where the first answer is wrong and the search
# has to write down the separation it missed and ask again.
_TWO_TRIANGLES = physical({
    ("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0,
    ("d", "e"): 1.0, ("e", "f"): 1.0, ("d", "f"): 1.0,
    ("c", "d"): 1.0,
})
_TRIANGLE_SITES = ("a", "b", "c", "d", "e", "f")
_TRIANGLES_CHOICE = _chosen(_TWO_TRIANGLES, _TRIANGLE_SITES)


def test_the_segment_the_first_answer_missed_is_bought_once_it_is_written_down() -> None:
    """The one segment joining the two triangles is bought, though no site's row asks for it.

    There is one requirement for every way of separating a site from its peers, far too many
    to write out, so they are written down as an answer violates them. Every site here holds
    two ways out inside its own triangle, so the first answer buys the six triangle segments
    and nothing joins ``a`` to ``d`` at all. A search that stopped there would publish two
    backbones and call them one.
    """
    assert ("c", "d") in _TRIANGLES_CHOICE.segments


# Twelve cities of carrier fiber with five backbone seats, the one graph here whose search
# runs long enough to be cut short. Every fixture above is answered by the first solve or
# the one after it, so none of them could ever reach a limit on how many passes the search
# may take; this one takes 26. See ``fixtures.MANY_PASS_SEGMENTS``.
_MANY_PASS = physical(fixtures.MANY_PASS_SEGMENTS)
_MANY_PASS_INPUTS = FiberInputs(
    fixtures.MANY_PASS_SITES, _MANY_PASS, _all_distances(_MANY_PASS), _WAYS_OUT, 1
)
_MANY_PASS_CHOICE = _chosen(_MANY_PASS, fixtures.MANY_PASS_SITES)
_MANY_PASS_FIBER = admissible_fiber(_MANY_PASS_INPUTS)


def test_a_search_that_runs_long_enough_buys_the_shortest_synthesis_there_is() -> None:
    """This map's choice runs the 159 miles of its own floor, so nothing shorter meets it.

    The floor is the fewest miles any synthesis meeting these requirements could run, so a
    choice that lands on it is not close to the shortest synthesis -- it is the shortest
    synthesis. Reaching it takes 26 passes of writing down a requirement the answer missed and
    solving again.

    A limit of 24 passes stood in the module until GitHub issue #63 and stopped this search
    short of that. What it bought instead was thirteen segments running 291 miles against
    the same floor of 159 -- 132 miles of fiber the tenant pays for every month and gets
    nothing for. Every one of the six real tenants needed hundreds of passes, 645 for DAF
    and 1,382 for AFGSC, so all six were bought this way.
    """
    assert _bought_miles(_MANY_PASS_CHOICE, _MANY_PASS) == pytest.approx(
        _MANY_PASS_CHOICE.lower_bound_miles
    )


def test_the_fiber_a_long_search_settles_on_meets_every_requirement_asked_of_it() -> None:
    """Nothing is left short by the fiber this map's search bought, on the fiber alone.

    The miles above say the choice is the shortest one there is; this says it is a choice at
    all. Both are needed, because the cheapest way to run few miles is to buy fiber that
    leaves a site short, and a synthesis is measured for that only much later, by
    ``synthesizer.validation.backbone_mesh_independence_deficient``, on a report an operator
    reads rather than on the fiber the synthesis stands on.
    """
    assert not _shortfalls(
        _requirements(_MANY_PASS_INPUTS, _MANY_PASS_FIBER),
        _held(_MANY_PASS_FIBER, _MANY_PASS_CHOICE.segments),
    )


# Every choice above beside the fiber it was made over, so the guarantee the whole module
# exists for can be stated once against all of them.
_CASES: tuple[tuple[str, FiberChoice, dict[tuple[str, str], PhysicalEdge]], ...] = (
    ("ring", _RING_CHOICE, _RING),
    ("ring and chord", _CHORD_CHOICE, _CHORD),
    ("chain", _CHAIN_CHOICE, _CHAIN),
    ("two triangles", _TRIANGLES_CHOICE, _TWO_TRIANGLES),
    ("pair with two ways round", _TWIN_CHOICE, _TWIN_WAYS),
    ("twelve cities and five seats", _MANY_PASS_CHOICE, _MANY_PASS),
)


def test_no_choice_is_floored_above_the_fiber_it_actually_bought() -> None:
    """Every synthesis here runs at least the miles its own floor says no synthesis can go below.

    The floor is the relaxation's answer over every requirement the search wrote down, and
    the synthesis is one answer to those same requirements, so the synthesis cannot be shorter than
    the floor. A floor above the fiber bought would be arithmetic that has come apart, and it
    would be published on every synthesis as ``backbone_lower_bound_miles`` and read as a
    tenant's network being shorter than anything that could meet its own requirements.
    """
    assert [
        name
        for name, choice, edges in _CASES
        if choice.lower_bound_miles > _bought_miles(choice, edges) + _SLACK
    ] == []
