"""Unit tests for how many independent links a backbone node's fiber can carry.

Each substrate here is built so the answer is countable by eye, because the ceiling is
what both selection and validation are then held to: it decides how many links a node
reaches for and how many it is asked for. A wrong ceiling would move both at once.
"""

from __future__ import annotations

import pytest

import fixtures
from synthesizer.ceiling import (
    StretchLimit,
    independent_route_ceiling,
    independent_routes,
    diverse_path_ceilings,
)
from synthesizer.graphs import build_adjacency, distances_from

physical = fixtures.physical_edges_from


# Boston in miniature: three fiber spans leave ``bos``, but every route to the rest of
# the backbone crosses ``alb`` or ``stm`` -- the third span doubles back to ``alb``. So
# the fiber degree is three and the ceiling is two, which is the distinction the number
# exists to draw.
_TWO_CUTS = build_adjacency(physical({
    ("bos", "alb"): 1.0, ("bos", "stm"): 1.0, ("bos", "x"): 1.0, ("x", "alb"): 1.0,
    ("alb", "n1"): 1.0, ("stm", "n2"): 1.0, ("n1", "n2"): 1.0,
}))
_TWO_CUT_BACKBONE = ("bos", "n1", "n2")


def test_the_ceiling_is_the_number_of_cuts_not_of_fiber_spans() -> None:
    """Three spans leave bos, but all routes cross alb or stm, so its ceiling is two."""
    assert independent_route_ceiling("bos", _TWO_CUT_BACKBONE, _TWO_CUTS) == 2


# The same shape with one chokepoint instead of two: every route out of ``bos`` crosses
# ``alb``, including the one that leaves on a span of its own and doubles back.
_ONE_CUT = build_adjacency(physical({
    ("bos", "alb"): 1.0, ("bos", "x"): 1.0, ("x", "alb"): 1.0,
    ("alb", "n1"): 1.0, ("alb", "n2"): 1.0, ("n1", "n2"): 1.0,
}))


def test_a_node_behind_one_chokepoint_has_a_ceiling_of_one() -> None:
    """Two spans leave bos and both routes cross alb, so one city takes everything."""
    assert independent_route_ceiling("bos", ("bos", "n1", "n2"), _ONE_CUT) == 1


# Two internally-disjoint routes from ``s`` reach the same peer ``t``, and the only other
# backbone node sits behind ``t``. Both routes die when t's city does, so together they
# are one independent link rather than two.
_TWIN_ROUTES = build_adjacency(physical({
    ("s", "p1"): 1.0, ("s", "p2"): 1.0, ("p1", "t"): 1.0, ("p2", "t"): 1.0,
    ("t", "u"): 1.0,
}))


def test_two_routes_to_one_peer_count_once() -> None:
    """Disjoint routes to the same peer both fail with that peer, so the ceiling is one."""
    assert independent_route_ceiling("s", ("s", "t", "u"), _TWIN_ROUTES) == 1


def test_an_unreachable_node_has_no_ceiling_at_all() -> None:
    """A node the substrate does not carry can hold no link, so its ceiling is zero."""
    assert independent_route_ceiling("nowhere", ("nowhere", "n1", "n2"), _ONE_CUT) == 0


def test_the_ceilings_are_computed_for_every_backbone_node() -> None:
    """The per-node pass answers for each backbone node, not just the one asked about."""
    assert diverse_path_ceilings(_TWO_CUT_BACKBONE, _TWO_CUTS) == {"bos": 2, "n1": 2, "n2": 2}


# The count is only ever as good as the routes behind it, and something has to be able to
# wire them: a node the mesh leaves short is repaired by taking the very routes counted
# here, so these check the count can be shown its working rather than only asserted.
_BOS_ROUTES = independent_routes("bos", _TWO_CUT_BACKBONE, _TWO_CUTS)


def test_the_counted_routes_run_from_the_node_to_distinct_peers() -> None:
    """Each counted route is one link, so they leave bos and land on a peer apiece."""
    assert sorted((route[0], route[-1]) for route in _BOS_ROUTES) == [
        ("bos", "n1"), ("bos", "n2")
    ]


def test_the_counted_routes_share_no_intermediate_city() -> None:
    """No city carries two of them, which is the whole of what independence means."""
    inner = [city for route in _BOS_ROUTES for city in route[1:-1]]
    assert sorted(inner) == sorted(set(inner))


# The Pacific in miniature, and the first fixture here whose spans are not all the same
# length. ``sea`` reaches both of its peers overland through ``pdx``, ten miles a span, and
# reaches them again through ``tok`` a thousand miles away. The overland routes share
# ``pdx``, so a proof counting disjoint routes alone takes the ocean crossing as ``sea``'s
# second way out -- and prefers it, since a breadth-first augmenting search takes the route
# crossing the fewest cities and the crossing is the shortest such route there is.
_PACIFIC = physical({
    ("sea", "pdx"): 10.0, ("pdx", "hil"): 10.0, ("pdx", "eug"): 10.0,
    ("sea", "tok"): 1000.0, ("tok", "hil"): 1000.0, ("tok", "eug"): 1000.0,
})
_PACIFIC_ADJACENCY = build_adjacency(_PACIFIC)
_PACIFIC_BACKBONE = ("eug", "hil", "sea")
# 2,000 miles of cable to cover the twenty ``sea`` is from either peer overland, so the
# crossing runs a hundred times the direct route and a bound of three refuses it.
_PACIFIC_LIMIT = StretchLimit(3.0, distances_from(_PACIFIC_ADJACENCY, _PACIFIC_BACKBONE))


def test_a_route_far_longer_than_the_direct_one_is_not_proved() -> None:
    """No route out of sea is laid through tok once the stretch bound is applied."""
    routes = independent_routes(
        "sea", _PACIFIC_BACKBONE, _PACIFIC_ADJACENCY, _PACIFIC_LIMIT
    )
    assert not [route for route in routes if "tok" in route]


def test_the_ceiling_counts_usable_routes_rather_than_merely_disjoint_ones() -> None:
    """sea holds one link, not two: everything it can use runs through pdx.

    Without the bound the ocean crossing counts and sea scores two, which is the ceiling
    inflation that credits a site with protection its fiber cannot deliver.
    """
    assert independent_route_ceiling(
        "sea", _PACIFIC_BACKBONE, _PACIFIC_ADJACENCY, _PACIFIC_LIMIT
    ) == 1


def test_the_unbounded_ceiling_still_counts_the_crossing() -> None:
    """Omitting the limit leaves the old behaviour exactly, which is what the callers rely on."""
    assert independent_route_ceiling(
        "sea", _PACIFIC_BACKBONE, _PACIFIC_ADJACENCY
    ) == 2


def test_a_crossing_that_is_the_only_way_to_a_peer_is_kept() -> None:
    """The bound refuses a detour, not an ocean: the sole route to a peer is admissible.

    ``syd`` hangs off ``tok`` and no overland fiber reaches it, so the crossing is the
    shortest route to it rather than a hundred times the shortest, and a bound measured
    against the direct distance has nothing to say against it. Compare
    :func:`test_a_route_far_longer_than_the_direct_one_is_not_proved`, which is the same
    fiber with nothing on the far side of the crossing worth reaching.

    That the crossing survives is all this asserts. Which peer the flow then spends it on
    is not something a max flow promises -- it takes the fewest-city route each round and
    any peer beyond ``tok`` is the same one city away -- so an assertion naming ``syd``
    would be pinning an ordering rather than the bound.
    """
    spans = {**_PACIFIC, **physical({("tok", "syd"): 1000.0})}
    adjacency = build_adjacency(spans)
    backbone = ("eug", "hil", "sea", "syd")
    routes = independent_routes(
        "sea", backbone, adjacency, StretchLimit(3.0, distances_from(adjacency, backbone))
    )
    assert [route for route in routes if "tok" in route] != []


def test_a_limit_missing_the_measured_site_is_refused() -> None:
    """A bound with no distances from the site is an error, not a ceiling of zero.

    Every budget would be unmeasurable and every span would fail the test, so the site
    would score nothing at all -- which reads as fiber that can hold no link and lowers
    the site's target to match, on the strength of a caller's omission rather than the
    substrate. It is named so the caller can see which row is missing.
    """
    limit = StretchLimit(3.0, distances_from(_PACIFIC_ADJACENCY, ("eug", "hil")))
    with pytest.raises(ValueError, match="sea"):
        independent_routes("sea", _PACIFIC_BACKBONE, _PACIFIC_ADJACENCY, limit)
