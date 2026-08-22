"""Unit tests for how many independent links a backbone node's fiber can carry.

Each set of fiber here is built so the answer is countable by eye, because the ceiling is
what both selection and validation are then held to: it decides how many links a node
reaches for and how many it is asked for. A wrong ceiling would move both at once.
"""

from __future__ import annotations

import pytest

import fixtures
from synthesizer.ceiling import (
    BackupPathLimit,
    PathProofInputs,
    independent_path_ceiling,
    independent_paths,
    diverse_path_ceilings,
)
from synthesizer.graphs import adjacency_by_carrier, build_adjacency, distances_from
from synthesizer.input_graph import FiberSegment

physical = fixtures.fiber_segments_from


def _path_miles(
    path: tuple[str, ...], adjacency: dict[str, list[tuple[str, float]]]
) -> float:
    """How many fiber miles one proved path runs on, segment by segment."""
    return sum(
        weight
        for left, right in zip(path, path[1:])
        for neighbor, weight in adjacency[left]
        if neighbor == right
    )


# Boston in miniature: three fiber segments leave ``bos``, but every path to the rest of
# the backbone crosses ``alb`` or ``stm`` -- the third segment doubles back to ``alb``. So
# the fiber degree is three and the ceiling is two, which is the distinction the number
# exists to draw.
_TWO_CUTS = build_adjacency(physical({
    ("bos", "alb"): 1.0, ("bos", "stm"): 1.0, ("bos", "x"): 1.0, ("x", "alb"): 1.0,
    ("alb", "n1"): 1.0, ("stm", "n2"): 1.0, ("n1", "n2"): 1.0,
}))
_TWO_CUT_BACKBONE = ("bos", "n1", "n2")


def test_the_ceiling_is_the_number_of_cuts_not_of_fiber_segments() -> None:
    """Three segments leave bos, but all paths cross alb or stm, so its ceiling is two."""
    assert independent_path_ceiling("bos", PathProofInputs(_TWO_CUT_BACKBONE, _TWO_CUTS)) == 2


# The same shape with one single point of failure instead of two: every path out of ``bos`` crosses
# ``alb``, including the one that leaves on a segment of its own and doubles back.
_ONE_CUT = build_adjacency(physical({
    ("bos", "alb"): 1.0, ("bos", "x"): 1.0, ("x", "alb"): 1.0,
    ("alb", "n1"): 1.0, ("alb", "n2"): 1.0, ("n1", "n2"): 1.0,
}))


def test_a_node_behind_one_failure_point_has_a_ceiling_of_one() -> None:
    """Two segments leave bos and both paths cross alb, so one city takes everything."""
    assert independent_path_ceiling("bos", PathProofInputs(("bos", "n1", "n2"), _ONE_CUT)) == 1


# Two internally-disjoint paths from ``s`` reach the same peer ``t``, and the only other
# backbone node sits behind ``t``. Both paths die when t's city does, so together they
# are one independent link rather than two.
_TWIN_PATHS = build_adjacency(physical({
    ("s", "p1"): 1.0, ("s", "p2"): 1.0, ("p1", "t"): 1.0, ("p2", "t"): 1.0,
    ("t", "u"): 1.0,
}))


def test_two_paths_to_one_peer_count_once() -> None:
    """Disjoint paths to the same peer both fail with that peer, so the ceiling is one.

    ``s`` has ``u`` to reach as well, so a second path to ``t`` gains it nothing a way out
    to ``u`` would not gain better. A site with no other peer to reach is the case where the
    answer changes, and it is the two tests below.
    """
    assert independent_path_ceiling("s", PathProofInputs(("s", "t", "u"), _TWIN_PATHS)) == 1


# The same twin paths with the backbone cut down to the pair they join. ``s`` has one peer
# and no way to two paths except two paths to it, which is Two-Node: a backbone of Ashburn,
# VA and Salt Lake City, UT and a tenant asking for two (GitHub issue #58).
_ONE_PEER = ("s", "t")


def test_a_site_with_one_peer_holds_the_paths_it_was_asked_for() -> None:
    """Two paths asked for and one peer to reach, so that peer carries both of them."""
    inputs = PathProofInputs(_ONE_PEER, _TWIN_PATHS, paths_wanted=2)
    assert independent_path_ceiling("s", inputs) == 2


def test_the_paths_to_one_peer_share_no_city_but_that_peer() -> None:
    """Sharing the destination is what they are for; sharing anything else is not."""
    inner = [
        city
        for path in independent_paths("s", PathProofInputs(_ONE_PEER, _TWIN_PATHS, paths_wanted=2))
        for city in path[1:-1]
    ]
    assert sorted(inner) == sorted(set(inner))


def test_a_site_with_one_peer_is_still_held_to_one_path_when_one_is_asked() -> None:
    """The doubling up answers the tenant's number; it is not what the fiber allows."""
    inputs = PathProofInputs(_ONE_PEER, _TWIN_PATHS, paths_wanted=1)
    assert independent_path_ceiling("s", inputs) == 1


def test_a_site_seated_below_the_seats_its_config_allows_takes_one_path_to_a_peer() -> None:
    """A tenant that allows six seats has asked for a network of peers, not a pair joined twice.

    The seats the config allows are what say whether a site has another peer to reach, and
    a run that seated two of six is a synthesis short of sites. Counting the sites it seated
    instead would have this site double up on the one peer in front of it (GitHub issue #59).
    """
    ground = PathProofInputs(_ONE_PEER, _TWIN_PATHS, paths_wanted=2, seat_cap=6)
    assert independent_path_ceiling("s", ground) == 1


# Three ways from ``s`` to its only peer ``t``, sharing no city, at two, four and six miles.
# A tenant asking for two is owed the two shortest and not the third.
_THREE_WAYS = build_adjacency(physical({
    ("s", "near"): 1.0, ("near", "t"): 1.0,
    ("s", "mid"): 2.0, ("mid", "t"): 2.0,
    ("s", "far"): 3.0, ("far", "t"): 3.0,
}))


def test_no_more_paths_to_one_peer_are_proved_than_were_asked_for() -> None:
    """Three ways to the one peer and two asked for, so the third is left unproved."""
    inputs = PathProofInputs(_ONE_PEER, _THREE_WAYS, paths_wanted=2)
    assert independent_path_ceiling("s", inputs) == 2


def test_the_paths_proved_to_one_peer_are_the_shortest_of_them() -> None:
    """The six-mile way round is the one left out, not either of the two shorter ones."""
    paths = independent_paths("s", PathProofInputs(_ONE_PEER, _THREE_WAYS, paths_wanted=2))
    assert sorted(path[1] for path in paths) == ["mid", "near"]


def test_an_unreachable_node_has_no_ceiling_at_all() -> None:
    """A node the merged carriers do not carry can hold no link, so its ceiling is zero."""
    inputs = PathProofInputs(("nowhere", "n1", "n2"), _ONE_CUT)
    assert independent_path_ceiling("nowhere", inputs) == 0


def test_the_ceilings_are_computed_for_every_backbone_node() -> None:
    """The per-node pass answers for each backbone node, not just the one asked about."""
    assert diverse_path_ceilings(PathProofInputs(_TWO_CUT_BACKBONE, _TWO_CUTS)) == {
        "bos": 2, "n1": 2, "n2": 2
    }


# The count is only ever as good as the paths behind it, and something has to be able to
# wire them: a node the mesh leaves short is repaired by taking the very paths counted
# here, so these check the count can be shown its working rather than only asserted.
_BOS_PATHS = independent_paths("bos", PathProofInputs(_TWO_CUT_BACKBONE, _TWO_CUTS))


def test_the_counted_paths_run_from_the_node_to_distinct_peers() -> None:
    """Each counted path is one link, so they leave bos and land on a peer apiece."""
    assert sorted((path[0], path[-1]) for path in _BOS_PATHS) == [
        ("bos", "n1"), ("bos", "n2")
    ]


def test_the_counted_paths_share_no_intermediate_city() -> None:
    """No city carries two of them, which is the whole of what independence means."""
    inner = [city for path in _BOS_PATHS for city in path[1:-1]]
    assert sorted(inner) == sorted(set(inner))


# Two ways to each peer, and the fewest-city one is the long one. ``sea`` reaches ``hil``
# over a single express segment of a hundred miles or over two one-mile segments through
# ``pdx``, and reaches ``eug`` the same way through ``tac``. Both sets are two paths and
# neither shares a city, so nothing but the mileage tells them apart: the fewest-city set
# runs 200 miles and the least-mileage set runs 4. It is the smallest fixture that can tell
# a proof choosing by city count from one choosing by distance (GitHub issue #57).
_EXPRESS_SEGMENTS = build_adjacency(physical({
    ("sea", "hil"): 100.0, ("sea", "eug"): 100.0,
    ("sea", "pdx"): 1.0, ("pdx", "hil"): 1.0,
    ("sea", "tac"): 1.0, ("tac", "eug"): 1.0,
}))
_EXPRESS_BACKBONE = ("eug", "hil", "sea")


def test_the_paths_proved_are_the_shortest_set_of_that_size() -> None:
    """sea's two ways out run four miles in all, not the two hundred the express segments do.

    This is the assertion the whole of GitHub issue #57 reduces to. The paths are laid
    verbatim by ``synthesizer.backbone.backbone_mesh``, so the fiber this picks is
    fiber the synthesis orders, and picking the express segments ordered fifty times as much of
    it for exactly the same protection.
    """
    assert sum(
        _path_miles(path, _EXPRESS_SEGMENTS)
        for path in independent_paths("sea", PathProofInputs(_EXPRESS_BACKBONE, _EXPRESS_SEGMENTS))
    ) == 4.0


def test_taking_the_shortest_set_costs_the_site_none_of_its_paths() -> None:
    """sea still holds two ways out, so choosing on mileage costs it nothing.

    A path lost is protection lost, and the ceiling is what
    :func:`synthesizer.stages.finalize` holds a site to, so a shorter set one path smaller
    would lower the site's target and silence the check on it.
    """
    inputs = PathProofInputs(_EXPRESS_BACKBONE, _EXPRESS_SEGMENTS)
    assert independent_path_ceiling("sea", inputs) == 2


# The Pacific in miniature. ``sea`` reaches both of its peers overland through ``pdx``, ten
# miles a segment, and reaches them again through ``tok`` a thousand miles away. The overland
# paths share ``pdx``, so ``sea``'s second way out to a distinct peer has to be the ocean
# crossing whatever the proof costs its paths by -- a proof maximises how many paths it
# finds before it minimises what they run on, which is why the bound below is still needed
# and cannot be replaced by preferring short paths.
_PACIFIC = physical({
    ("sea", "pdx"): 10.0, ("pdx", "hil"): 10.0, ("pdx", "eug"): 10.0,
    ("sea", "tok"): 1000.0, ("tok", "hil"): 1000.0, ("tok", "eug"): 1000.0,
})
_PACIFIC_ADJACENCY = build_adjacency(_PACIFIC)
_PACIFIC_BACKBONE = ("eug", "hil", "sea")
# 2,000 miles of fiber to cover the twenty ``sea`` is from either peer overland, so the
# crossing runs a hundred times the direct distance and a bound of three refuses it.
_PACIFIC_LIMIT = BackupPathLimit(3.0, distances_from(_PACIFIC_ADJACENCY, _PACIFIC_BACKBONE))


def test_a_path_far_longer_than_the_direct_one_is_not_proved() -> None:
    """No path out of sea is laid through tok once the backup path multiple is applied."""
    paths = independent_paths(
        "sea", PathProofInputs(_PACIFIC_BACKBONE, _PACIFIC_ADJACENCY, _PACIFIC_LIMIT)
    )
    assert not [path for path in paths if "tok" in path]


def test_the_ceiling_counts_usable_paths_rather_than_merely_disjoint_ones() -> None:
    """sea holds one link, not two: everything it can use runs through pdx.

    Without the bound the ocean crossing counts and sea scores two, which is the ceiling
    inflation that credits a site with protection its fiber cannot deliver.
    """
    assert independent_path_ceiling(
        "sea", PathProofInputs(_PACIFIC_BACKBONE, _PACIFIC_ADJACENCY, _PACIFIC_LIMIT)
    ) == 1


def test_the_unbounded_ceiling_still_counts_the_crossing() -> None:
    """Omitting the limit leaves the old behaviour exactly, which is what the callers rely on."""
    assert independent_path_ceiling(
        "sea", PathProofInputs(_PACIFIC_BACKBONE, _PACIFIC_ADJACENCY)
    ) == 2


# The same Pacific fiber with a peer on the far side of the crossing. ``syd`` hangs off
# ``tok`` and no overland fiber reaches it, so here the crossing is the shortest path to a
# peer rather than a hundred times the shortest, and it is the fiber a repair must not
# throw away while it is throwing away the detour above.
#
# ``syd`` sits five hundred miles beyond ``tok`` rather than a thousand, so it is strictly
# the nearest thing across the ocean. Left at a thousand it would tie with ``hil`` and
# ``eug``, and which peer the crossing landed on would be decided by nothing.
_SOLE_CROSSING_ADJACENCY = build_adjacency(
    {**_PACIFIC, **physical({("tok", "syd"): 500.0})}
)
_SOLE_CROSSING_BACKBONE = ("eug", "hil", "sea", "syd")
_SOLE_CROSSING_LIMIT = BackupPathLimit(
    3.0, distances_from(_SOLE_CROSSING_ADJACENCY, _SOLE_CROSSING_BACKBONE)
)


def test_a_crossing_that_is_the_only_way_to_a_peer_is_kept() -> None:
    """The crossing is proved where it is the only way to a peer, cost it what it may.

    Two things could drop it and both would be wrong. The bound refuses a detour, not an
    ocean: ``syd`` hangs off ``tok`` and no overland fiber reaches it, so the crossing is
    the shortest path to it rather than a hundred times the shortest, and a bound measured
    against the direct distance has nothing to say against it. And a proof that priced its
    paths by mileage would avoid fifteen hundred miles of ocean given any alternative --
    here there is none, and a path to one more peer is worth more than the fiber it runs
    on. Compare :func:`test_a_path_far_longer_than_the_direct_one_is_not_proved`, which is
    the same fiber with nothing on the far side of the crossing worth reaching.
    """
    paths = independent_paths(
        "sea",
        PathProofInputs(_SOLE_CROSSING_BACKBONE, _SOLE_CROSSING_ADJACENCY, _SOLE_CROSSING_LIMIT),
    )
    assert [path for path in paths if "tok" in path] != []


def test_a_site_whose_second_way_out_is_a_crossing_still_scores_two() -> None:
    """Measuring the finished paths must not win its accuracy by discarding them.

    ``sea`` reaches ``syd`` across the ocean and reaches ``hil`` and ``eug`` overland, so
    both of its ways out are usable and the honest count is two. A repair that answered an
    overrunning path by withdrawing the crossing itself would score ``sea`` at one, lower
    its target to match, and silence the check on it -- which is the quiet pass the count
    exists to avoid, arrived at from the other side.
    """
    assert independent_path_ceiling(
        "sea",
        PathProofInputs(_SOLE_CROSSING_BACKBONE, _SOLE_CROSSING_ADJACENCY, _SOLE_CROSSING_LIMIT),
    ) == 2


def test_a_limit_missing_the_measured_site_is_refused() -> None:
    """A bound with no distances from the site is an error, not a ceiling of zero.

    Every budget would be unmeasurable and every segment would fail the test, so the site
    would score nothing at all -- which reads as fiber that can hold no link and lowers
    the site's target to match, on the strength of a caller's omission rather than the
    fiber. It is named so the caller can see which row is missing.
    """
    limit = BackupPathLimit(3.0, distances_from(_PACIFIC_ADJACENCY, ("eug", "hil")))
    with pytest.raises(ValueError, match="sea"):
        independent_paths("sea", PathProofInputs(_PACIFIC_BACKBONE, _PACIFIC_ADJACENCY, limit))


# Five segments, and the fewest that can hold the defect GitHub issue #45 reports. ``sea``
# sits ten miles from ``pdx``, which is ten miles from the peer ``hil`` and seven thousand
# from the peer ``syd``; ``sea`` also reaches ``tok`` a thousand miles off, and ``tok``
# reaches ``hil`` a thousand miles beyond that. Both ``tok`` segments lie inside syd's
# twenty-one-thousand-mile allowance and neither is anywhere near hil's sixty, so a check
# reading segments keeps them and a check reading paths does not. Only ``pdx`` reaches
# ``syd``, so one of sea's two paths must spend ``pdx`` and the other is left the
# crossing -- which lands it on ``hil``, the peer whose allowance never covered it.
_LEAK_ADJACENCY = build_adjacency(physical({
    ("sea", "pdx"): 10.0, ("pdx", "hil"): 10.0, ("pdx", "syd"): 7000.0,
    ("sea", "tok"): 1000.0, ("tok", "hil"): 1000.0,
}))
_LEAK_BACKBONE = ("hil", "sea", "syd")
_LEAK_LIMIT = BackupPathLimit(3.0, distances_from(_LEAK_ADJACENCY, _LEAK_BACKBONE))


def _multiples(
    node: str,
    backbone_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    limit: BackupPathLimit,
) -> dict[tuple[str, ...], float]:
    """Every path proved out of ``node``, by the multiple of the shortest path it ran.

    All of them rather than only the ones that overrun, so the assertion reads as a whole
    value and names any path that comes back along with how far it went. A path inside
    its allowance scores at most the multiple the limit carries; the leak scored a hundred.
    """
    return {
        path: _path_miles(path, adjacency) / limit.distances[node][path[-1]]
        for path in independent_paths(node, PathProofInputs(backbone_ids, adjacency, limit))
    }


def test_no_proved_path_runs_further_than_the_peer_it_ends_at_allows() -> None:
    """sea's paths are held to the peers they reach, not to the peer that kept their fiber.

    This is the assertion the whole of GitHub issue #45 reduces to. Before it, the path
    ``sea -> tok -> hil`` came back proved as well: 2,000 miles of fiber to cover the twenty
    ``sea`` is from ``hil`` overland, a hundred times an allowance of sixty, and every segment
    of it admissible because ``syd`` sits far enough away to justify them.

    What comes back is the one path to ``syd``, which runs the shortest way there is.
    """
    assert _multiples("sea", _LEAK_BACKBONE, _LEAK_ADJACENCY, _LEAK_LIMIT) == {
        ("sea", "pdx", "syd"): 1.0
    }


def test_the_site_whose_path_leaked_is_scored_at_the_one_it_can_use() -> None:
    """sea holds one link, not the two the path through tok credited it with.

    The count is what :func:`synthesizer.stages.finalize` holds a site to, so a repair
    reaching only the paths would leave the number that sets the target still saying two
    -- and an operator still reading a shortfall they cannot close.
    """
    ground = PathProofInputs(_LEAK_BACKBONE, _LEAK_ADJACENCY, _LEAK_LIMIT)
    assert diverse_path_ceilings(ground)["sea"] == 1


# A path that overruns while no single segment on it can be shown impossible, which is where
# withdrawing segments runs out. ``sea`` has two ways out, ``pdx`` and ``tac``, and two peers,
# ``hil`` 105 miles off through ``pdx`` and ``syd`` 7,025 miles off behind it. Only ``pdx``
# and ``tac`` reach ``syd``, so the two paths take one way out each, and the shortest pair
# spends ``pdx`` on ``syd``: 7,025 miles plus the 400 that ``sea -> tac -> hil`` runs, against
# 13,305 for the pair the other way round. That leaves ``hil`` reached over two 200-mile
# segments against an allowance of 315. Neither segment can be refused, each being measured
# against the shortest way to and from its own ends -- 50 miles from ``sea`` to ``tac`` over
# the small hops, 105 from ``tac`` back to ``hil`` -- so they come to 305 and 250 against
# that same 315, while the path they make together comes to 400.
_UNWITHDRAWABLE_ADJACENCY = build_adjacency(physical({
    ("sea", "pdx"): 25.0, ("pdx", "tac"): 25.0, ("pdx", "hil"): 80.0,
    ("sea", "tac"): 200.0, ("tac", "hil"): 200.0,
    ("pdx", "syd"): 7000.0, ("tac", "syd"): 13000.0,
}))
_UNWITHDRAWABLE_BACKBONE = ("hil", "sea", "syd")
_UNWITHDRAWABLE_LIMIT = BackupPathLimit(
    3.0, distances_from(_UNWITHDRAWABLE_ADJACENCY, _UNWITHDRAWABLE_BACKBONE)
)


def test_a_path_no_segment_of_which_can_be_refused_is_dropped_rather_than_counted() -> None:
    """An overrunning path nothing can be withdrawn from is not credited to the site.

    Neither segment of ``sea -> tac -> hil`` can be shown impossible, so there is nothing to
    withdraw and no second pass to find the pair that would have worked -- ``sea -> pdx ->
    hil`` at 105 miles beside ``sea -> tac -> syd`` at 13,200, both inside their peers'
    allowances. ``sea`` scores one where the honest answer is two.

    That is the method's limit rather than an oversight, and it is written down as a test
    because a reader of the number needs to know the number can come out under. The site is
    named in ``backbone_diverse_paths_ceiling_limited`` when it does, so a target the tool
    lowered is read rather than inferred.
    """
    assert independent_path_ceiling(
        "sea",
        PathProofInputs(
            _UNWITHDRAWABLE_BACKBONE, _UNWITHDRAWABLE_ADJACENCY, _UNWITHDRAWABLE_LIMIT
        ),
    ) == 1


# Two ways from ``s`` to ``t``, each two hops through a city of its own. Who has the fiber
# on those hops is the whole of the difference between the two maps: in the first every
# way out changes hands halfway, in the second each way out is one company's from end to
# end. The geometry is identical, so anything that separates them is the ownership.
_CHANGES_HANDS = fixtures.carrier_fiber_segments({
    ("s", "x"): (1.0, ("lumen",)),
    ("x", "t"): (1.0, ("zayo",)),
    ("s", "y"): (1.0, ("lumen",)),
    ("y", "t"): (1.0, ("zayo",)),
})
_ONE_COMPANY_EACH = fixtures.carrier_fiber_segments({
    ("s", "x"): (1.0, ("lumen",)),
    ("x", "t"): (1.0, ("lumen",)),
    ("s", "y"): (1.0, ("zayo",)),
    ("y", "t"): (1.0, ("zayo",)),
})


def _owned_proof(
    fiber: dict[tuple[str, str], FiberSegment], paths_wanted: int = 1
) -> PathProofInputs:
    """A proof over fiber that says who owns it, so the ways out are proved per carrier."""
    return PathProofInputs(
        ("s", "t"),
        build_adjacency(fiber),
        paths_wanted=paths_wanted,
        fiber_by_carrier=adjacency_by_carrier(fiber),
    )


def test_a_way_out_that_changes_hands_is_no_way_out() -> None:
    """No carrier has both hops, so there is no path anybody could be asked to quote."""
    assert not independent_paths("s", _owned_proof(_CHANGES_HANDS))


def test_ways_out_may_come_from_different_carriers() -> None:
    """Two ways out, one wholly Lumen and one wholly Zayo, are both real and both drawn."""
    assert sorted(independent_paths("s", _owned_proof(_ONE_COMPANY_EACH, 2))) == [
        ("s", "x", "t"), ("s", "y", "t"),
    ]


def test_the_same_fiber_joins_the_pair_when_nobody_owns_it() -> None:
    """The identical geometry with no owners recorded still draws a way out."""
    assert independent_paths("s", PathProofInputs(("s", "t"), build_adjacency(
        physical({("s", "x"): 1.0, ("x", "t"): 1.0, ("s", "y"): 1.0, ("y", "t"): 1.0}),
    ))) == [("s", "x", "t")]


# Fiber both companies have between the same two cities, so both of them come back with
# the same way out and the merge has to notice they are one path rather than two.
_BOTH_HAVE_IT = fixtures.carrier_fiber_segments({("s", "t"): (1.0, ("lumen", "zayo"))})
# Lumen goes straight through ``x`` to the peer; Zayo goes through ``x`` and on round
# ``u``. The two ways out are different paths that both stand on ``x``, so losing that one
# city would take both and only the shorter can be counted.
_SHARE_A_CITY = fixtures.carrier_fiber_segments({
    ("s", "x"): (1.0, ("lumen", "zayo")),
    ("x", "t"): (1.0, ("lumen",)),
    ("x", "u"): (1.0, ("zayo",)),
    ("u", "t"): (1.0, ("zayo",)),
})


def test_a_way_out_both_carriers_have_is_drawn_once() -> None:
    """One length of fiber two companies both sell is one way out, not two."""
    assert independent_paths("s", _owned_proof(_BOTH_HAVE_IT)) == [("s", "t")]


def test_a_way_out_standing_on_a_city_already_spent_is_not_drawn() -> None:
    """Zayo's way round also leans on x, which Lumen's shorter one already spent."""
    assert independent_paths("s", _owned_proof(_SHARE_A_CITY)) == [("s", "x", "t")]


def test_one_peer_takes_one_way_out_however_many_carriers_offer_one() -> None:
    """A site with peers to spare is not credited twice for reaching the same one."""
    assert independent_paths("s", _owned_proof(_ONE_COMPANY_EACH)) == [("s", "x", "t")]
