"""Unit tests for how many ways out of a city its carriers could be asked to quote.

An operator orders a path from one company and pays that company for it every month, so a
way out of a site assembled from two companies' fiber is not a product anybody sells
(GitHub issue #106). The helper asks each carrier on its own over its own fiber and adds
the answers, which is what an operator really does: one path from each of several
companies rather than one path from none of them.

What it is for is holding a published ceiling against a source outside the build that
produced it. A build that counted a site's ways out over everybody's fiber at once would
credit it with ways out nobody sells, and a floor priced for those sits above the fiber the
network beside it actually ordered -- Yurop published 8,844.892 miles against a floor of
9,141.641 it had already beaten (GitHub issue #111). Boston, MA is the shape that did it,
and the first fixture below is Boston: fiber in three directions, three owners, and only
one of them reaching anywhere the tenant pins.

The number is bounded from above rather than measured exactly, on purpose. Two carriers'
answers may cross the same city, and a city carrying two ways out is one way out the moment
it goes, so what an operator could really hold is at most this. Erring high leaves a sound
ceiling passing and erring low would fail a healthy network, which is the worse of the two.
"""

from __future__ import annotations

from test_published_syntheses import sellable_ways_out

# Boston's three ways out, owned separately: Zayo's through Albany, NY carries on to the
# one city this tenant pins, Lumen's through Stamford, CT reaches nothing else that
# matters. So the geometry offers two ways out of Boston and the ownership sells one.
_ASHBURN = "Ashburn, VA"
_BOSTON = "Boston, MA"
_SPLIT = {
    "zayo": {
        frozenset({_BOSTON, "Albany, NY"}),
        frozenset({"Albany, NY", _ASHBURN}),
    },
    "lumen": {frozenset({_BOSTON, "Stamford, CT"})},
}
# The same three cities of Zayo fiber, with Lumen's way out carried through to a second
# pinned city instead of stopping. Both carriers now have something to quote.
_NEW_YORK = "New York, NY"
_OWNED = {
    "zayo": {
        frozenset({_BOSTON, "Albany, NY"}),
        frozenset({"Albany, NY", _ASHBURN}),
    },
    "lumen": {
        frozenset({_BOSTON, "Stamford, CT"}),
        frozenset({"Stamford, CT", _NEW_YORK}),
    },
}
# Two ways round between a pair of seats, both of them one carrier's. A backbone of two
# seats has one peer to reach, so the peer ends both ways out rather than one.
_PAIR = {
    "zayo": {
        frozenset({_BOSTON, "Albany, NY"}),
        frozenset({"Albany, NY", _ASHBURN}),
        frozenset({_BOSTON, "Stamford, CT"}),
        frozenset({"Stamford, CT", _ASHBURN}),
    },
}
# The same way out held by two companies, which is two quotes for one way out and not two
# ways out. Fiber from Boston to itself is in there as well: it carries nobody anywhere.
_BOTH_QUOTE = {
    "zayo": {frozenset({_BOSTON, _ASHBURN}), frozenset({_BOSTON})},
    "lumen": {frozenset({_BOSTON, _ASHBURN})},
}


def test_a_city_whose_second_way_out_changes_hands_can_be_sold_only_the_first() -> None:
    """Boston is sold one way out, though its fiber runs in two directions that matter.

    Zayo's fiber carries Boston as far as Ashburn, VA and Lumen's stops at Stamford, CT, so
    the second way out exists only if the two are stitched together, and nobody quotes that.
    A build crediting Boston with two prices its floor for a way out no operator can buy.
    """
    assert sellable_ways_out(_SPLIT, _BOSTON, frozenset({_ASHBURN}), 1) == 1


def test_a_city_is_sold_a_way_out_by_each_carrier_that_has_one() -> None:
    """Two carriers with a way out apiece sell Boston two, which is what an operator holds.

    The behaviour the lowering above must not break: a site's ways out may be bought from
    several companies, one path each. It is the stitching that nobody sells, not the buying
    from more than one.
    """
    assert sellable_ways_out(
        _OWNED, _BOSTON, frozenset({_ASHBURN, _NEW_YORK}), 1
    ) == 2


def test_one_peer_may_end_more_than_one_way_out_where_there_is_only_one_peer() -> None:
    """Two ways round to the single peer of a two-seat backbone are two ways out.

    A backbone capped at two seats has one peer to reach, so a tenant asking for two ways
    out can only be answered by two paths to it, and the peer stops being a city a way out
    is charged for. This is Two-Node's shape.
    """
    assert sellable_ways_out(_PAIR, _BOSTON, frozenset({_ASHBURN}), 2) == 2


def test_no_more_ways_out_are_counted_than_the_peers_can_end() -> None:
    """Two companies quoting the same way out is two quotes and one way out.

    A way out is charged for the peer it reaches, so one peer allowed to end one of them
    ends one however many companies would sell it. Fiber from Boston to itself is in this
    fixture too, and carries nobody anywhere.
    """
    assert sellable_ways_out(_BOTH_QUOTE, _BOSTON, frozenset({_ASHBURN}), 1) == 1


def test_a_city_no_carrier_has_fiber_at_can_be_sold_nothing() -> None:
    """A city no carrier's file names has no way out to sell, which is the truth about it.

    It is what a fabricated twin looks like from out here: the operator lays the fiber into
    it themselves, and no carrier's file records a length of it.
    """
    assert sellable_ways_out(_SPLIT, "Huntingdon, United Kingdom", frozenset({_ASHBURN}), 1) == 0
