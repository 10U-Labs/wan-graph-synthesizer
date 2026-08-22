from __future__ import annotations

from test_published_syntheses import sellable_ways_out

_ASHBURN = "Ashburn, VA"
_BOSTON = "Boston, MA"
_SPLIT = {
    "zayo": {
        frozenset({_BOSTON, "Albany, NY"}),
        frozenset({"Albany, NY", _ASHBURN}),
    },
    "lumen": {frozenset({_BOSTON, "Stamford, CT"})},
}
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
_PAIR = {
    "zayo": {
        frozenset({_BOSTON, "Albany, NY"}),
        frozenset({"Albany, NY", _ASHBURN}),
        frozenset({_BOSTON, "Stamford, CT"}),
        frozenset({"Stamford, CT", _ASHBURN}),
    },
}
_BOTH_QUOTE = {
    "zayo": {frozenset({_BOSTON, _ASHBURN}), frozenset({_BOSTON})},
    "lumen": {frozenset({_BOSTON, _ASHBURN})},
}


def test_a_city_whose_second_way_out_changes_hands_can_be_sold_only_the_first() -> None:
    assert sellable_ways_out(_SPLIT, _BOSTON, frozenset({_ASHBURN}), 1) == 1


def test_a_city_is_sold_a_way_out_by_each_carrier_that_has_one() -> None:
    assert sellable_ways_out(
        _OWNED, _BOSTON, frozenset({_ASHBURN, _NEW_YORK}), 1
    ) == 2


def test_one_peer_may_end_more_than_one_way_out_where_there_is_only_one_peer() -> None:
    assert sellable_ways_out(_PAIR, _BOSTON, frozenset({_ASHBURN}), 2) == 2


def test_no_more_ways_out_are_counted_than_the_peers_can_end() -> None:
    assert sellable_ways_out(_BOTH_QUOTE, _BOSTON, frozenset({_ASHBURN}), 1) == 1


def test_a_city_no_carrier_has_fiber_at_can_be_sold_nothing() -> None:
    assert sellable_ways_out(_SPLIT, "Huntingdon, United Kingdom", frozenset({_ASHBURN}), 1) == 0
