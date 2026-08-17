"""Unit tests for how many independent links a backbone node's fiber can carry.

Each substrate here is built so the answer is countable by eye, because the ceiling is
what both selection and validation are then held to: it decides how many links a node
reaches for and how many it is asked for. A wrong ceiling would move both at once.
"""

from __future__ import annotations

import pytest

import fixtures
from synthesizer.ceiling import (
    BackupRouteLimit,
    independent_route_ceiling,
    independent_routes,
    diverse_path_ceilings,
)
from synthesizer.graphs import build_adjacency, distances_from

physical = fixtures.physical_edges_from


def _route_miles(
    route: tuple[str, ...], adjacency: dict[str, list[tuple[str, float]]]
) -> float:
    """How much cable one proved route runs on, span by span."""
    return sum(
        weight
        for left, right in zip(route, route[1:])
        for neighbor, weight in adjacency[left]
        if neighbor == right
    )


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
    """Disjoint routes to the same peer both fail with that peer, so the ceiling is one.

    ``s`` has ``u`` to reach as well, so a second route to ``t`` buys it nothing a way out
    to ``u`` would not buy better. A site with no other peer to reach is the case where the
    answer changes, and it is the two tests below.
    """
    assert independent_route_ceiling("s", ("s", "t", "u"), _TWIN_ROUTES) == 1


# The same twin routes with the backbone cut down to the pair they join. ``s`` has one peer
# and no way to two paths except two routes to it, which is Two-Node: a backbone of Ashburn,
# VA and Salt Lake City, UT and a tenant asking for two (GitHub issue #58).
_ONE_PEER = ("s", "t")


def test_a_site_with_one_peer_holds_the_paths_it_was_asked_for() -> None:
    """Two paths asked for and one peer to reach, so that peer carries both of them."""
    assert independent_route_ceiling("s", _ONE_PEER, _TWIN_ROUTES, None, 2) == 2


def test_the_routes_to_one_peer_share_no_city_but_that_peer() -> None:
    """Sharing the destination is what they are for; sharing anything else is not."""
    inner = [
        city
        for route in independent_routes("s", _ONE_PEER, _TWIN_ROUTES, None, 2)
        for city in route[1:-1]
    ]
    assert sorted(inner) == sorted(set(inner))


def test_a_site_with_one_peer_is_still_held_to_one_route_when_one_is_asked() -> None:
    """The doubling up answers the tenant's number; it is not what the fiber allows."""
    assert independent_route_ceiling("s", _ONE_PEER, _TWIN_ROUTES, None, 1) == 1


# Three ways from ``s`` to its only peer ``t``, sharing no city, at two, four and six miles.
# A tenant asking for two is owed the two shortest and not the third.
_THREE_WAYS = build_adjacency(physical({
    ("s", "near"): 1.0, ("near", "t"): 1.0,
    ("s", "mid"): 2.0, ("mid", "t"): 2.0,
    ("s", "far"): 3.0, ("far", "t"): 3.0,
}))


def test_no_more_routes_to_one_peer_are_proved_than_were_asked_for() -> None:
    """Three ways to the one peer and two asked for, so the third is left unproved."""
    assert independent_route_ceiling("s", _ONE_PEER, _THREE_WAYS, None, 2) == 2


def test_the_routes_proved_to_one_peer_are_the_shortest_of_them() -> None:
    """The six-mile way round is the one left out, not either of the two shorter ones."""
    routes = independent_routes("s", _ONE_PEER, _THREE_WAYS, None, 2)
    assert sorted(route[1] for route in routes) == ["mid", "near"]


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


# Two ways to each peer, and the fewest-city one is the long one. ``sea`` reaches ``hil``
# over a single express span of a hundred miles or over two one-mile spans through
# ``pdx``, and reaches ``eug`` the same way through ``tac``. Both sets are two routes and
# neither shares a city, so nothing but the cable tells them apart: the fewest-city set
# runs 200 miles and the least-mileage set runs 4. It is the smallest fixture that can tell
# a proof choosing by city count from one choosing by distance (GitHub issue #57).
_EXPRESS_SPANS = build_adjacency(physical({
    ("sea", "hil"): 100.0, ("sea", "eug"): 100.0,
    ("sea", "pdx"): 1.0, ("pdx", "hil"): 1.0,
    ("sea", "tac"): 1.0, ("tac", "eug"): 1.0,
}))
_EXPRESS_BACKBONE = ("eug", "hil", "sea")


def test_the_routes_proved_are_the_shortest_set_of_that_size() -> None:
    """sea's two ways out run four miles in all, not the two hundred the express spans do.

    This is the assertion the whole of GitHub issue #57 reduces to. The routes are laid
    verbatim by ``synthesizer.backbone.diverse_mesh_routes``, so the fiber this picks is
    cable the design orders, and picking the express spans ordered fifty times as much of
    it for exactly the same protection.
    """
    assert sum(
        _route_miles(route, _EXPRESS_SPANS)
        for route in independent_routes("sea", _EXPRESS_BACKBONE, _EXPRESS_SPANS)
    ) == 4.0


def test_taking_the_shortest_set_costs_the_site_none_of_its_routes() -> None:
    """sea still holds two ways out, so choosing on mileage buys its cable with nothing.

    A route lost is protection lost, and the ceiling is what
    :func:`synthesizer.stages.finalize` holds a site to, so a cheaper set one route smaller
    would lower the site's target and silence the check on it.
    """
    assert independent_route_ceiling("sea", _EXPRESS_BACKBONE, _EXPRESS_SPANS) == 2


# The Pacific in miniature. ``sea`` reaches both of its peers overland through ``pdx``, ten
# miles a span, and reaches them again through ``tok`` a thousand miles away. The overland
# routes share ``pdx``, so ``sea``'s second way out to a distinct peer has to be the ocean
# crossing whatever the proof costs its routes by -- a proof maximises how many routes it
# finds before it minimises what they run on, which is why the bound below is still needed
# and cannot be replaced by preferring short routes.
_PACIFIC = physical({
    ("sea", "pdx"): 10.0, ("pdx", "hil"): 10.0, ("pdx", "eug"): 10.0,
    ("sea", "tok"): 1000.0, ("tok", "hil"): 1000.0, ("tok", "eug"): 1000.0,
})
_PACIFIC_ADJACENCY = build_adjacency(_PACIFIC)
_PACIFIC_BACKBONE = ("eug", "hil", "sea")
# 2,000 miles of cable to cover the twenty ``sea`` is from either peer overland, so the
# crossing runs a hundred times the direct route and a bound of three refuses it.
_PACIFIC_LIMIT = BackupRouteLimit(3.0, distances_from(_PACIFIC_ADJACENCY, _PACIFIC_BACKBONE))


def test_a_route_far_longer_than_the_direct_one_is_not_proved() -> None:
    """No route out of sea is laid through tok once the backup route multiple is applied."""
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


# The same Pacific fiber with a peer on the far side of the crossing. ``syd`` hangs off
# ``tok`` and no overland fiber reaches it, so here the crossing is the shortest route to a
# peer rather than a hundred times the shortest, and it is the fiber a repair must not
# throw away while it is throwing away the detour above.
#
# ``syd`` sits five hundred miles beyond ``tok`` rather than a thousand, so it is strictly
# the cheapest thing across the ocean. Left at a thousand it would tie with ``hil`` and
# ``eug``, and which peer the crossing landed on would be decided by nothing.
_SOLE_CROSSING_ADJACENCY = build_adjacency(
    {**_PACIFIC, **physical({("tok", "syd"): 500.0})}
)
_SOLE_CROSSING_BACKBONE = ("eug", "hil", "sea", "syd")
_SOLE_CROSSING_LIMIT = BackupRouteLimit(
    3.0, distances_from(_SOLE_CROSSING_ADJACENCY, _SOLE_CROSSING_BACKBONE)
)


def test_a_crossing_that_is_the_only_way_to_a_peer_is_kept() -> None:
    """The crossing is proved where it is the only way to a peer, cost it what it may.

    Two things could drop it and both would be wrong. The bound refuses a detour, not an
    ocean: ``syd`` hangs off ``tok`` and no overland fiber reaches it, so the crossing is
    the shortest route to it rather than a hundred times the shortest, and a bound measured
    against the direct distance has nothing to say against it. And a proof that priced its
    routes by mileage would avoid fifteen hundred miles of ocean given any alternative --
    here there is none, and a route to one more peer is worth more than the cable it runs
    on. Compare :func:`test_a_route_far_longer_than_the_direct_one_is_not_proved`, which is
    the same fiber with nothing on the far side of the crossing worth reaching.
    """
    routes = independent_routes(
        "sea", _SOLE_CROSSING_BACKBONE, _SOLE_CROSSING_ADJACENCY, _SOLE_CROSSING_LIMIT
    )
    assert [route for route in routes if "tok" in route] != []


def test_a_site_whose_second_way_out_is_a_crossing_still_scores_two() -> None:
    """Measuring the finished routes must not buy its accuracy by discarding them.

    ``sea`` reaches ``syd`` across the ocean and reaches ``hil`` and ``eug`` overland, so
    both of its ways out are usable and the honest count is two. A repair that answered an
    overrunning route by withdrawing the crossing itself would score ``sea`` at one, lower
    its target to match, and silence the check on it -- which is the quiet pass the count
    exists to avoid, arrived at from the other side.
    """
    assert independent_route_ceiling(
        "sea", _SOLE_CROSSING_BACKBONE, _SOLE_CROSSING_ADJACENCY, _SOLE_CROSSING_LIMIT
    ) == 2


def test_a_limit_missing_the_measured_site_is_refused() -> None:
    """A bound with no distances from the site is an error, not a ceiling of zero.

    Every budget would be unmeasurable and every span would fail the test, so the site
    would score nothing at all -- which reads as fiber that can hold no link and lowers
    the site's target to match, on the strength of a caller's omission rather than the
    substrate. It is named so the caller can see which row is missing.
    """
    limit = BackupRouteLimit(3.0, distances_from(_PACIFIC_ADJACENCY, ("eug", "hil")))
    with pytest.raises(ValueError, match="sea"):
        independent_routes("sea", _PACIFIC_BACKBONE, _PACIFIC_ADJACENCY, limit)


# Five spans, and the fewest that can hold the defect GitHub issue #45 reports. ``sea``
# sits ten miles from ``pdx``, which is ten miles from the peer ``hil`` and seven thousand
# from the peer ``syd``; ``sea`` also reaches ``tok`` a thousand miles off, and ``tok``
# reaches ``hil`` a thousand miles beyond that. Both ``tok`` spans lie inside syd's
# twenty-one-thousand-mile allowance and neither is anywhere near hil's sixty, so a check
# reading spans keeps them and a check reading routes does not. Only ``pdx`` reaches
# ``syd``, so one of sea's two routes must spend ``pdx`` and the other is left the
# crossing -- which lands it on ``hil``, the peer whose allowance never covered it.
_LEAK_ADJACENCY = build_adjacency(physical({
    ("sea", "pdx"): 10.0, ("pdx", "hil"): 10.0, ("pdx", "syd"): 7000.0,
    ("sea", "tok"): 1000.0, ("tok", "hil"): 1000.0,
}))
_LEAK_BACKBONE = ("hil", "sea", "syd")
_LEAK_LIMIT = BackupRouteLimit(3.0, distances_from(_LEAK_ADJACENCY, _LEAK_BACKBONE))


def _multiples(
    node: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: BackupRouteLimit,
) -> dict[tuple[str, ...], float]:
    """Every route proved out of ``node``, by the multiple of the shortest route it ran.

    All of them rather than only the ones that overrun, so the assertion reads as a whole
    value and names any route that comes back along with how far it went. A route inside
    its allowance scores at most the multiple the limit carries; the leak scored a hundred.
    """
    return {
        route: _route_miles(route, adjacency) / limit.distances[node][route[-1]]
        for route in independent_routes(node, backbone_ids, adjacency, limit)
    }


def test_no_proved_route_runs_further_than_the_peer_it_ends_at_allows() -> None:
    """sea's routes are held to the peers they reach, not to the peer that kept their fiber.

    This is the assertion the whole of GitHub issue #45 reduces to. Before it, the route
    ``sea -> tok -> hil`` came back proved as well: 2,000 miles of cable to cover the twenty
    ``sea`` is from ``hil`` overland, a hundred times an allowance of sixty, and every span
    of it admissible because ``syd`` sits far enough away to justify them.

    What comes back is the one route to ``syd``, which runs the shortest way there is.
    """
    assert _multiples("sea", _LEAK_BACKBONE, _LEAK_ADJACENCY, _LEAK_LIMIT) == {
        ("sea", "pdx", "syd"): 1.0
    }


def test_the_site_whose_route_leaked_is_scored_at_the_one_it_can_use() -> None:
    """sea holds one link, not the two the route through tok credited it with.

    The count is what :func:`synthesizer.stages.finalize` holds a site to, so a repair
    reaching only the routes would leave the number that sets the target still saying two
    -- and an operator still reading a shortfall they cannot close.
    """
    assert diverse_path_ceilings(_LEAK_BACKBONE, _LEAK_ADJACENCY, _LEAK_LIMIT)["sea"] == 1


# A route that overruns while no single span on it can be shown impossible, which is where
# withdrawing spans runs out. ``sea`` has two ways out, ``pdx`` and ``tac``, and two peers,
# ``hil`` 105 miles off through ``pdx`` and ``syd`` 7,025 miles off behind it. Only ``pdx``
# and ``tac`` reach ``syd``, so the two routes take one way out each, and the cheapest pair
# spends ``pdx`` on ``syd``: 7,025 miles plus the 400 that ``sea -> tac -> hil`` runs, against
# 13,305 for the pair the other way round. That leaves ``hil`` reached over two 200-mile
# spans against an allowance of 315. Neither span can be refused, each being measured
# against the shortest way to and from its own ends -- 50 miles from ``sea`` to ``tac`` over
# the small hops, 105 from ``tac`` back to ``hil`` -- so they come to 305 and 250 against
# that same 315, while the route they make together comes to 400.
_UNWITHDRAWABLE_ADJACENCY = build_adjacency(physical({
    ("sea", "pdx"): 25.0, ("pdx", "tac"): 25.0, ("pdx", "hil"): 80.0,
    ("sea", "tac"): 200.0, ("tac", "hil"): 200.0,
    ("pdx", "syd"): 7000.0, ("tac", "syd"): 13000.0,
}))
_UNWITHDRAWABLE_BACKBONE = ("hil", "sea", "syd")
_UNWITHDRAWABLE_LIMIT = BackupRouteLimit(
    3.0, distances_from(_UNWITHDRAWABLE_ADJACENCY, _UNWITHDRAWABLE_BACKBONE)
)


def test_a_route_no_span_of_which_can_be_refused_is_dropped_rather_than_counted() -> None:
    """An overrunning route nothing can be withdrawn from is not credited to the site.

    Neither span of ``sea -> tac -> hil`` can be shown impossible, so there is nothing to
    withdraw and no second pass to find the pair that would have worked -- ``sea -> pdx ->
    hil`` at 105 miles beside ``sea -> tac -> syd`` at 13,200, both inside their peers'
    allowances. ``sea`` scores one where the honest answer is two.

    That is the method's limit rather than an oversight, and it is written down as a test
    because a reader of the number needs to know the number can come out under. The site is
    named in ``backbone_diverse_paths_ceiling_limited`` when it does, so a target the tool
    lowered is read rather than inferred.
    """
    assert independent_route_ceiling(
        "sea", _UNWITHDRAWABLE_BACKBONE, _UNWITHDRAWABLE_ADJACENCY, _UNWITHDRAWABLE_LIMIT
    ) == 1
