"""Unit tests for how much has to fail before a site is cut off from the peers it must reach.

What comes back from a search here is what the fiber is then bought against: a separation
becomes a row in the program saying "hold at least this much of the segments that cross
it", so a separation naming the wrong cities or the wrong fiber buys the wrong fiber, and a
separation reported where the fiber already carries what was asked buys fiber nobody needs.

Each graph is the smallest one that forces its own answer. Two sites joined by a single
segment can lose nothing but that segment, so the answer has to be fiber; a city with two
ways in and two ways out cannot be separated by any one segment, so the answer has to be
the city. Nothing here has two answers of the same size, which is what stops a test passing
on whichever largest flow the search happened to find first.
"""

from __future__ import annotations

from collections.abc import Mapping

from synthesizer.flow_cuts import Separation, SeparationQuestion, weakest_separation
from synthesizer.input_graph import link_key

# The site every question below is asked on behalf of, and the places a way out of it may
# end. ``a`` is spared by the search itself, since losing it loses the site rather than the
# protection between it and anywhere else.
_SITE = "a"
_ONE_PEER = frozenset({"b"})
_TWO_PEERS = frozenset({"b", "c"})
_NOTHING_SPARED: frozenset[str] = frozenset()

# The three answers the fixtures below come back with, named once so that two tests reading
# the same answer are visibly asking about the same thing.
_NOTHING_TO_BUY = Separation(frozenset(), frozenset())
_ONLY_THE_SEGMENT = Separation(frozenset(), frozenset({("a", "b")}))
_ONLY_THE_CITY = Separation(frozenset({"x"}), frozenset())


def _whole(*segments: tuple[str, str]) -> dict[tuple[str, str], float]:
    """These fiber segments, each of them bought outright."""
    return {link_key(left, right): 1.0 for left, right in segments}


def _asked(
    held: Mapping[tuple[str, str], float],
    required: int,
    peers: frozenset[str] = _ONE_PEER,
    spared: frozenset[str] = _NOTHING_SPARED,
) -> Separation | None:
    """The separation this much fiber cannot survive, asked of the ways out of ``a``."""
    return weakest_separation(SeparationQuestion(_SITE, peers, spared, held), required)


# Two sites and the one segment between them. There is no city in the middle to lose, so
# the only thing that can fail is the fiber itself -- which is what makes this the fixture
# that tells a separation of fiber apart from a separation of cities.
_DIRECT = _whole(("a", "b"))

# The same segment part-bought and not bought at all. A share of a segment carries that
# much of a way out and no more, and a segment nothing is held of carries none; both are
# still fiber a buyer would close the separation with, so both are still named.
_PART_BOUGHT: Mapping[tuple[str, str], float] = {("a", "b"): 0.5}
_UNBOUGHT: Mapping[tuple[str, str], float] = {("a", "b"): 0.0}

# Fiber that does not touch ``a`` at all, which is the case a site the carrier says nothing
# about arrives as.
_ELSEWHERE = _whole(("y", "z"))

# ``x`` with two ways in from ``a`` and two ways out to the peers ``b`` and ``c``. No single
# segment separates ``a`` from its peers here -- withdraw any one and another remains -- so
# the smallest thing that does is the city ``x``, and a second way out is something no
# amount of buying on this fiber can deliver.
_ROUND_ONE_CITY = _whole(("a", "x"), ("a", "p"), ("p", "x"), ("b", "x"), ("c", "x"))


def test_fiber_already_carrying_what_was_asked_reports_no_separation() -> None:
    """One way out asked for and one segment holding it, so there is nothing to report.

    A separation returned here would be bought against, and the fiber it named would be
    fiber the tenant's number never asked for.
    """
    assert _asked(_DIRECT, 1) is None


def test_asking_for_nothing_ends_before_any_searching() -> None:
    """A requirement of none is met by any fiber at all, including fiber holding nothing.

    It is the requirement a site already served past its tenant's number arrives with, and
    the answer is settled by the number rather than by walking the fiber for it.
    """
    assert _asked(_DIRECT, 0) is None


def test_a_site_the_fiber_does_not_reach_has_nothing_to_buy() -> None:
    """Fiber that does not touch ``a`` leaves it separated from its peers by nothing at all.

    No city fails and no segment crosses, because the site stands on none of this fiber.
    Reporting a segment here would tell a buyer to order fiber that would still leave the
    site where it is.
    """
    assert _asked(_ELSEWHERE, 1) == _NOTHING_TO_BUY


def test_two_sites_joined_by_one_segment_are_separated_by_that_segment() -> None:
    """Two ways out asked for over a single segment, so the segment is the whole separation.

    Nothing sits between ``a`` and ``b`` to be lost, so the fiber is what fails and the
    fiber is what is named -- the one form the answer can take that a buyer can act on.
    """
    assert _asked(_DIRECT, 2) == _ONLY_THE_SEGMENT


def test_a_segment_held_in_part_carries_only_that_much_of_a_way_out() -> None:
    """Half a segment is half a way out, so one way out asked for is one way out short.

    A search counting a part-bought segment as a whole one would report the requirement met
    and stop the program buying the rest of it.
    """
    assert _asked(_PART_BOUGHT, 1) == _ONLY_THE_SEGMENT


def test_a_segment_nothing_is_held_of_is_still_the_fiber_to_buy() -> None:
    """A segment held at none of itself crosses the separation and is named anyway.

    This is the whole point of naming the fiber rather than the flow: the answer is what
    buying would close the separation with, and buying starts from nothing.
    """
    assert _asked(_UNBOUGHT, 1) == _ONLY_THE_SEGMENT


def test_the_city_every_way_out_crosses_is_what_the_fiber_cannot_survive() -> None:
    """Both ways out of ``a`` cross ``x``, so ``x`` is the separation and no segment is.

    ``a`` reaches ``x`` twice over and ``x`` reaches both peers, so no single segment
    separates the site from them. A search reading only fiber would find nothing to name
    and report a requirement met that one city's loss takes away.
    """
    assert _asked(_ROUND_ONE_CITY, 2, peers=_TWO_PEERS) == _ONLY_THE_CITY


def test_sparing_that_city_leaves_the_same_fiber_carrying_both_ways_out() -> None:
    """The same fiber, with ``x`` unable to fail, carries the two ways out that were asked for.

    Which cities may fail is the whole difference between the two answers, and it is what
    :func:`synthesizer.validation.diverse_path_count` draws as well: a city a way out ends
    at is a destination, not protection between here and there.
    """
    assert _asked(_ROUND_ONE_CITY, 2, peers=_TWO_PEERS, spared=frozenset({"x"})) is None


def test_a_peer_the_fiber_does_not_carry_is_left_out_of_the_count() -> None:
    """A place named as a peer that no fiber reaches ends no way out, so nothing is bought.

    ``a`` still stands on its segment to ``b`` and the search still runs over it; what it
    reports is that there is no fiber to buy, rather than a separation naming segments that
    would bring the named place no closer.
    """
    assert _asked(_DIRECT, 1, peers=frozenset({"nowhere"})) == _NOTHING_TO_BUY
