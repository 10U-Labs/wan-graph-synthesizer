"""Unit tests for the paths a backbone is drawn with over the fiber it was chosen with.

``synthesizer.backbone`` no longer decides anything one pair of sites at a time. The fiber
is chosen for the whole synthesis at once by ``synthesizer.survivable``, each site's ways out
are read off that fiber, and every path nobody needs is taken back out. So the cases here
are about the finished list of paths rather than about the order four passes ran in: which
pairs ended up joined, which fiber each path took, and which paths were dropped again.

Two graphs carry almost all of it. The square is four sites on a ring of hundred-mile
segments with two chords at two hundred and fifty, so the only synthesis that gives every site
two ways out is the ring itself and both the count and the mileage are forced. The
shared-egress graph is the shape GitHub issue #60 is about: the fewest-mile way from ``hub``
to ``q`` runs through ``m``, which is a city ``hub`` already stands on to reach ``p``, and a
slightly longer way through ``n`` does not. A synthesis that decides one pair at a time takes
the shorter way and leaves ``hub`` with one way out; a synthesis that chooses the whole thing
at once takes the longer one.
"""

from __future__ import annotations

import fixtures
from synthesizer.ceiling import BackupPathLimit
from synthesizer.input_graph import FiberSegment, link_key
from synthesizer.model import LINK_FOR_PIN, LINK_FOR_TARGET, SynthesisPath
from synthesizer.backbone import (
    BackboneConstraints,
    BackboneMesh,
    _needed,
    backbone_mesh,
    path_geometry_miles,
)
from synthesizer.survivable import FiberInputs, choose_fiber
from synthesizer.synthesize import all_pairs_shortest
from synthesizer.graphs import (
    adjacency_by_carrier,
    articulation_points,
    build_adjacency,
    path_link_keys,
)

pop = fixtures.carrier_pop
physical = fixtures.fiber_segments_from


def _distances(
    links: dict[tuple[str, str], FiberSegment],
) -> dict[str, dict[str, float]]:
    """How far apart every two cities on one fiber map are, measured over that fiber."""
    cities = sorted({city for pair in links for city in pair})
    distances, _predecessors = all_pairs_shortest(
        [pop(city) for city in cities], build_adjacency(links)
    )
    return distances


def _drawn(
    sites: tuple[str, ...],
    links: dict[tuple[str, str], FiberSegment],
    constraints: BackboneConstraints,
) -> BackboneMesh:
    """The mesh a whole fiber choice and assembly settles on over one graph."""
    return backbone_mesh(sites, _distances(links), links, constraints)


def _bought(
    links: dict[tuple[str, str], FiberSegment],
    sites: tuple[str, ...],
    constraints: BackboneConstraints,
) -> frozenset[tuple[str, str]]:
    """The fiber the choice buys for this backbone, asked on the same terms the mesh asks.

    ``backbone_mesh`` does not hand the choice's answer back, so it is asked again here with
    the inputs ``_bought_fiber`` builds. What the two have to agree about is which segments
    come back, and that is what the assertion standing on this compares.
    """
    return choose_fiber(FiberInputs(
        sites, links, _distances(links), constraints.number_of_diverse_paths,
        constraints.seat_cap, constraints.limit, adjacency_by_carrier(links),
    )).segments


def _bounded(
    links: dict[tuple[str, str], FiberSegment], multiple: float, asked_for: int = 2
) -> BackboneConstraints:
    """An operator's instructions carrying a backup path multiple over this fiber.

    ``_TWO_WAYS_OUT`` above carries none, which is right for the ring fixtures: on a ring a
    site has two fiber directions and takes both whatever the bound says. It is not right
    wherever the question is which of several ways out a site reaches for, since a bound is
    what leaves the long ones undrawn.
    """
    return BackboneConstraints(
        number_of_diverse_paths=asked_for, seat_cap=4,
        limit=BackupPathLimit(multiple, _distances(links)),
    )


def _pairs(mesh: BackboneMesh) -> set[tuple[str, str]]:
    """Every pair of sites the mesh joined, however many paths it joined them with."""
    return {link_key(use.source, use.target) for use in mesh.paths}


def _mesh_miles(mesh: BackboneMesh) -> float:
    """The fiber miles every path in the mesh runs on, added up."""
    return sum(use.distance_miles for use in mesh.paths)


def _cut(mesh: BackboneMesh) -> set[str]:
    """The cities whose loss would split the fiber the mesh's paths run over.

    Asked of the paths the mesh publishes rather than of the fiber they were chosen out of,
    because a network an operator holds is the paths they ordered and nothing else.
    """
    segments = {key for use in mesh.paths for key in path_link_keys(use.path)}
    return articulation_points({city for pair in segments for city in pair}, segments)


def _joining(mesh: BackboneMesh, left: str, right: str) -> SynthesisPath:
    """The path the mesh drew between one pair of sites."""
    return next(
        use
        for use in mesh.paths
        if link_key(use.source, use.target) == link_key(left, right)
    )


# Four sites on a ring of hundred-mile segments, with the two chords priced at two hundred
# and fifty. Every site needs two ways out and has only two fiber directions to find them
# in, so the ring is the whole of the answer: four paths, four hundred miles, and neither
# chord bought. The chords are what make it an answer rather than the only graph there is.
_SQUARE_SITES = ("w", "x", "y", "z")
_SQUARE_LINKS = physical({
    ("w", "x"): 100.0, ("x", "y"): 100.0, ("y", "z"): 100.0, ("z", "w"): 100.0,
    ("w", "y"): 250.0, ("x", "z"): 250.0,
})
_TWO_WAYS_OUT = BackboneConstraints(number_of_diverse_paths=2, seat_cap=4)
_SQUARE = _drawn(_SQUARE_SITES, _SQUARE_LINKS, _TWO_WAYS_OUT)


def test_the_square_is_drawn_with_one_path_a_pair_round_the_ring() -> None:
    """Four sites needing two ways out each are joined round the ring and nowhere else."""
    assert _pairs(_SQUARE) == {
        link_key("w", "x"), link_key("x", "y"), link_key("y", "z"), link_key("z", "w"),
    }


def test_the_square_buys_neither_of_the_chords() -> None:
    """A chord costs two hundred and fifty miles and buys nobody a way out, so it is not bought.

    The old passes could reach for one: a chord is the shortest way between the two sites it
    joins, and a pass drawing that pair on its own had no way to see that the ring already
    gave both of them everything they were owed.
    """
    assert _SQUARE_LINKS.keys() - {
        link_key(*pair) for use in _SQUARE.paths for pair in zip(use.path, use.path[1:])
    } == {link_key("w", "y"), link_key("x", "z")}


def test_the_square_runs_the_fewest_miles_its_fiber_allows() -> None:
    """Four hundred miles: every site owes two ways out, so four segments is the floor."""
    assert _mesh_miles(_SQUARE) == 400.0


def test_the_square_publishes_the_floor_it_was_judged_against() -> None:
    """The fewest miles any synthesis meeting the same requirements could run is four hundred.

    Each of the four sites needs two ways out, so the segments the synthesis holds add to at
    least four however they are shared out, and the four shortest are the ring.
    """
    assert round(_SQUARE.lower_bound_miles, 3) == 400.0


def test_the_square_runs_no_further_than_twice_the_floor() -> None:
    """The guarantee the whole choice exists for, asserted rather than assumed."""
    assert _mesh_miles(_SQUARE) <= 2 * _SQUARE.lower_bound_miles


def test_every_path_the_square_draws_says_a_site_reached_for_it() -> None:
    """No path is in the synthesis on the tool's own account; each one answers a site's number."""
    assert {use.reason for use in _SQUARE.paths} == {LINK_FOR_TARGET}


def test_a_path_names_both_of_the_sites_that_reached_for_it() -> None:
    """A path has two ends and both of them are reaching for it, so both are recorded.

    Which end asked is what separates a site's own path from one it holds because a peer
    needed it, and that is the whole of what ``unrequested_mesh_links`` reports.
    """
    assert _joining(_SQUARE, "w", "x").requested_by == ("w", "x")


def test_no_path_the_square_holds_could_be_taken_back_out() -> None:
    """Removing any one path leaves a site with one way out where its tenant bought two."""
    assert _needed(_SQUARE.paths, _SQUARE_SITES, 2) == _SQUARE.paths


# The shape GitHub issue #60 is about. ``hub`` reaches ``p`` and ``q`` through ``m`` at ten
# miles a segment, and reaches ``q`` again through ``n`` at eleven. Drawing hub-to-q on its
# own takes the twenty-mile way through ``m``, which leaves both of hub's paths riding one
# city; the twenty-two-mile way through ``n`` is the one that gives hub a second way out. The
# p-to-q segment closes the ring, so a whole-synthesis choice buys five segments and 52 miles.
_EGRESS_SITES = ("hub", "p", "q")
_EGRESS_LINKS = physical({
    ("hub", "m"): 10.0, ("m", "p"): 10.0, ("m", "q"): 10.0,
    ("hub", "n"): 11.0, ("n", "q"): 11.0, ("p", "q"): 10.0,
})
_EGRESS = _drawn(_EGRESS_SITES, _EGRESS_LINKS, BackboneConstraints(
    number_of_diverse_paths=2, seat_cap=3,
))


def test_the_longer_way_round_a_shared_city_is_the_one_drawn() -> None:
    """hub reaches q through n at twenty-two miles rather than through m at twenty.

    This is the narrowest statement of the defect. The way through ``m`` is shorter and is
    built from a segment hub's path to ``p`` already rides, so taking it would leave one
    city's loss taking both of hub's paths. Deciding the pair on its own cannot see that;
    deciding the whole synthesis can.
    """
    assert ("hub", "n", "q") in {use.path for use in _EGRESS.paths}


def test_the_shorter_way_round_that_shared_city_is_not_bought_at_all() -> None:
    """The m-to-q segment is fiber the finished synthesis never orders."""
    assert link_key("m", "q") not in {
        link_key(*pair) for use in _EGRESS.paths for pair in zip(use.path, use.path[1:])
    }


def test_the_shared_egress_graph_joins_all_three_pairs_once() -> None:
    """Three sites, three pairs, one path each: nothing is joined twice and nothing is left out."""
    assert len(_EGRESS.paths) == 3


def test_the_shared_egress_synthesis_runs_the_miles_its_five_segments_cost() -> None:
    """Fifty-two miles, which is the five segments the choice bought read back as paths."""
    assert _mesh_miles(_EGRESS) == 52.0


def test_no_path_the_shared_egress_synthesis_holds_could_be_taken_back_out() -> None:
    """Every one of the three paths is the second way out of one of the three sites."""
    assert _needed(_EGRESS.paths, _EGRESS_SITES, 2) == _EGRESS.paths


# Two lobes of one company's fiber, joined cheaply through the city ``mid`` and expensively
# through ``w``. ``a`` and ``b`` sit on one side and ``c`` and ``d`` on the other, and every
# way out any of the four holds runs through ``mid``: the way through ``w`` is forty miles
# where ``b`` and ``c`` are ten apart, so it is past what the operator's backup path multiple
# buys for that pair and no site reaches for it. The network the reading draws therefore falls
# in two the day ``mid`` goes dark, which is the shape three of the five live tenants
# published (GitHub issue #112).
#
# The ring fixtures above cannot produce it. A ring site has two fiber directions, so its two
# ways out are the two ways round and their union is the ring itself -- a network no city's
# loss splits, whatever the code under test does.
_LOBE_SITES = ("a", "b", "c", "d")
_LOBE_LOBES: dict[tuple[str, str], tuple[float, tuple[str, ...]]] = {
    ("a", "b"): (10.0, ("lumen",)),
    ("a", "mid"): (15.0, ("lumen",)),
    ("b", "mid"): (5.0, ("lumen",)),
    ("c", "d"): (10.0, ("lumen",)),
    ("c", "mid"): (5.0, ("lumen",)),
    ("d", "mid"): (15.0, ("lumen",)),
}
_LOBE_LINKS = fixtures.carrier_fiber_segments({
    **_LOBE_LOBES, ("b", "w"): (20.0, ("lumen",)), ("w", "c"): (20.0, ("lumen",)),
})
_TWO_LOBES = _drawn(_LOBE_SITES, _LOBE_LINKS, _bounded(_LOBE_LINKS, 3.0))
# The same two lobes with the way through ``w`` taken away, so no fiber at all goes past
# ``mid``.
_BOWTIE_LINKS = fixtures.carrier_fiber_segments(_LOBE_LOBES)
_BOWTIE = _drawn(_LOBE_SITES, _BOWTIE_LINKS, _bounded(_BOWTIE_LINKS, 3.0))
# The two lobes again under an operator who buys no path running more than four fifths again
# further than the straight distance between its two ends. The shortest way round ``mid`` is
# the fifty miles from ``a`` to ``c`` through ``w``, against the twenty those two are apart,
# so it is fiber this operator has already said they do not want.
_BOUNDED_LOBES = _drawn(_LOBE_SITES, _LOBE_LINKS, _bounded(_LOBE_LINKS, 1.8))
# The same two lobes for a tenant that asked for one way out of each node rather than two.
_ONE_WAY_OUT_LOBES = _drawn(_LOBE_SITES, _LOBE_LINKS, _bounded(_LOBE_LINKS, 3.0, 1))


def test_a_city_every_drawn_path_crosses_is_given_a_way_round_it() -> None:
    """No one city's loss splits the fiber the four seats are published over.

    The whole of what a tenant buying two ways out of every node is paying for, and the thing
    reading each site's ways out on its own does not deliver. Each seat holds two ways out
    either way; what the way round buys is the network staying in one piece when ``mid`` goes
    dark.
    """
    assert _cut(_TWO_LOBES) == set()


def test_the_path_drawn_round_that_city_is_one_company_can_sell() -> None:
    """The way round ``mid`` runs through ``w``, and Lumen has all of the fiber it crosses.

    An operator orders a path from one carrier end to end, so a way round assembled from two
    companies' fiber is not a thing anybody quotes. Exactly one path in the network crosses
    that fiber, which is the second half of what this says: the relief is one path and not a
    handful.
    """
    assert [
        use.carrier
        for use in _TWO_LOBES.paths
        if link_key("b", "w") in path_link_keys(use.path)
    ] == ["lumen"]


def test_a_city_no_fiber_goes_round_still_leaves_every_seat_its_paths() -> None:
    """A bowtie has no way round its waist, and every one of the four seats is still drawn.

    A single point of failure on the carrier's own fiber is a shortfall to report rather
    than a build to fail, so what comes back is the network the fiber allows.
    ``backbone_mesh_survives_any_one_site_loss`` is what says the operator cannot have what
    they asked for here.
    """
    assert {
        end for use in _BOWTIE.paths for end in (use.source, use.target)
    } == set(_LOBE_SITES)


def test_a_way_round_past_the_operators_backup_path_multiple_is_not_bought() -> None:
    """``mid`` stays a single point of failure where the only way round it runs too far.

    The bound is the operator's own ``backbone.max_backup_path_multiple``, and a path past
    it is one they would not order. Buying it anyway would hand them fiber they have already
    said they do not want, on the strength of a property they also want.
    """
    assert "mid" in _cut(_BOUNDED_LOBES)


def test_a_tenant_that_bought_one_way_out_is_not_given_a_way_round_anything() -> None:
    """The fiber through ``w`` goes unbought, which is the way round ``mid`` and nothing else.

    One way out is one way out, and a network built to it comes apart wherever its fiber
    does. Yurop asks for one diverse path, and four cities split the network it was handed;
    that is what it bought. Buying it the way round anyway would order fiber against a
    requirement the tenant did not write down, which is the same defect read backwards.
    """
    assert [
        use.path
        for use in _ONE_WAY_OUT_LOBES.paths
        if link_key("b", "w") in path_link_keys(use.path)
    ] == []


# The two graphs ``test_survivable.py`` uses to hold the choice to what one carrier sells and
# to what the operator's bound allows, driven the whole way through the mesh. The choice is
# only worth making if the network is drawn over what it chose, and until GitHub issue #113 it
# was not: ``_ways_out_of`` proved each site over the bought fiber and over the carriers'
# whole map and drew whichever gave more, which was the whole map for 29 of the 37 backbone
# seats ``etc/`` declares.
_SELLABLE_WAYS = fixtures.carrier_fiber_segments({
    ("a", "p"): (1.0, ("zayo",)),
    ("b", "p"): (1.0, ("lumen",)),
    ("a", "q"): (1.0, ("zayo",)),
    ("b", "q"): (1.0, ("lumen",)),
    ("a", "r"): (5.0, ("lumen",)),
    ("b", "r"): (5.0, ("lumen",)),
})
_SELLABLE_SITES = ("a", "b")
_SELLABLE_TERMS = BackboneConstraints(number_of_diverse_paths=2, seat_cap=2)
_SELLABLE_MESH = _drawn(_SELLABLE_SITES, _SELLABLE_WAYS, _SELLABLE_TERMS)
_NEAR_AND_FAR = physical({
    ("a", "b"): 1.0,
    ("a", "q"): 2.0, ("b", "q"): 2.0,
    ("a", "far"): 100.0, ("b", "far"): 100.0,
})
_NEAR_AND_FAR_SITES = ("a", "b", "far")
_NEAR_AND_FAR_TERMS = _bounded(_NEAR_AND_FAR, 3.0)
_NEAR_AND_FAR_MESH = _drawn(_NEAR_AND_FAR_SITES, _NEAR_AND_FAR, _NEAR_AND_FAR_TERMS)


def _run_over(mesh: BackboneMesh) -> set[tuple[str, str]]:
    """Every fiber segment the paths a mesh publishes actually run on."""
    return {key for use in mesh.paths for key in path_link_keys(use.path)}


def test_a_site_is_drawn_over_fiber_one_carrier_could_sell_it() -> None:
    """Every segment the two sites are drawn over is one the choice bought for them.

    Choosing the fiber is the expensive step of a build and the one the whole synthesizer is
    arranged around, so a network drawn over fiber the choice never picked is a choice made
    for nothing.
    """
    assert _run_over(_SELLABLE_MESH) <= _bought(
        _SELLABLE_WAYS, _SELLABLE_SITES, _SELLABLE_TERMS
    )


def test_a_site_is_drawn_over_fiber_the_operators_bound_allows() -> None:
    """The same, over the graph where the backup path multiple is what settles the answer.

    The two halves of the defect were separate: one was who owns the fiber and the other was
    how far a path may run, and either on its own left the drawing reaching past what the
    choice had bought.
    """
    assert _run_over(_NEAR_AND_FAR_MESH) <= _bought(
        _NEAR_AND_FAR, _NEAR_AND_FAR_SITES, _NEAR_AND_FAR_TERMS
    )


# The square again with one pair struck out by the operator, and again with one pinned. A
# pruned pair is a pair no path may end at, and a pinned pair is one that is joined whatever
# the choice of fiber said; the chord is pinned rather than a ring segment because no synthesis
# over this graph reaches for it, so what the pin does cannot be mistaken for what the
# choice would have done anyway.
_PRUNED = _drawn(_SQUARE_SITES, _SQUARE_LINKS, BackboneConstraints(
    removed_pairs=frozenset({link_key("w", "x")}), number_of_diverse_paths=2, seat_cap=4,
))
_PINNED_CHORD = _drawn(_SQUARE_SITES, _SQUARE_LINKS, BackboneConstraints(
    number_of_diverse_paths=2, forced_pairs=frozenset({link_key("w", "y")}), seat_cap=4,
))
_PINNED_SEGMENT = _drawn(_SQUARE_SITES, _SQUARE_LINKS, BackboneConstraints(
    number_of_diverse_paths=2, forced_pairs=frozenset({link_key("w", "x")}), seat_cap=4,
))


def test_a_pruned_pair_is_never_joined_by_a_drawn_path() -> None:
    """The operator struck the pair out, so no site's way out is allowed to end there."""
    assert link_key("w", "x") not in _pairs(_PRUNED)


def test_a_pruned_pair_leaves_the_rest_of_the_backbone_drawn() -> None:
    """Striking out one pair costs that pair its path and costs the other sites nothing."""
    assert link_key("y", "z") in _pairs(_PRUNED)


def test_a_pinned_pair_is_joined_however_the_fiber_was_chosen() -> None:
    """No synthesis over this graph reaches for the chord, so the pin is what joins the pair."""
    assert link_key("w", "y") in _pairs(_PINNED_CHORD)


def test_a_pinned_path_says_the_operator_is_what_put_it_there() -> None:
    """An operator reading a network larger than they asked for is owed the reason beside it."""
    assert _joining(_PINNED_CHORD, "w", "y").reason == LINK_FOR_PIN


def test_a_pinned_path_is_never_taken_back_out_as_unneeded() -> None:
    """The pin buys nobody a way out and stands anyway: it is the one path nobody justifies.

    Every site already holds its two ways out round the ring, so the pinned path would be
    dropped on the same test that drops any other path nobody needs. An operator instruction
    is honoured rather than second-guessed.
    """
    assert len(_PINNED_CHORD.paths) == 5


def test_a_pin_over_fiber_the_synthesis_would_have_bought_anyway_is_still_a_pin() -> None:
    """The pinned pair is one the ring joins too, and the pin is what the path is recorded as."""
    assert _joining(_PINNED_SEGMENT, "w", "x").reason == LINK_FOR_PIN


# Two sites the carrier's fiber never joins, pinned together by an operator who was wrong
# about the map. It is the one thing a pin cannot ask for, and the synthesis says so by drawing
# nothing rather than by failing.
_ISLANDS = physical({("a", "b"): 1.0, ("c", "d"): 1.0})
_ISLAND_PIN = _drawn(("a", "c"), _ISLANDS, BackboneConstraints(
    forced_pairs=frozenset({link_key("a", "c")}),
))


def test_a_backbone_the_fiber_never_joins_is_drawn_with_no_paths() -> None:
    """Two sites on separate fiber have no ways out to draw, pinned to each other or not."""
    assert not _ISLAND_PIN.paths


def test_a_backbone_the_fiber_never_joins_is_floored_at_nothing() -> None:
    """There is no fiber to choose from, so the fewest miles any synthesis could run is none."""
    assert _ISLAND_PIN.lower_bound_miles == 0.0


def test_a_site_the_fiber_does_not_carry_costs_the_others_nothing() -> None:
    """A site no fiber mentions draws no path, and the two the fiber does carry still join."""
    links = physical({("a", "b"): 1.0})
    mesh = _drawn(("a", "b", "zed"), links, BackboneConstraints(number_of_diverse_paths=1))
    assert _pairs(mesh) == {link_key("a", "b")}


def test_path_geometry_miles_adds_up_the_segments_a_path_crosses() -> None:
    """A path's mileage is the fiber it runs on, segment by segment."""
    assert path_geometry_miles(("w", "x", "y"), _SQUARE_LINKS) == 200.0


# Four hand-built syntheses the assembly would never produce, each one holding a path that has
# to be judged on a different ground. Written out rather than synthesized because each is a
# synthesis some other fiber choice could hand over, and the test is what the judgement does
# with it rather than how it came to be.
def _use(source: str, target: str, path: tuple[str, ...], miles: float) -> SynthesisPath:
    """One drawn path between two sites, over the cities named."""
    return SynthesisPath("backbone_mesh", source, target, path, miles)


_RING_PLUS_CHORD = [
    _use("w", "x", ("w", "x"), 100.0),
    _use("x", "y", ("x", "y"), 100.0),
    _use("y", "z", ("y", "z"), 100.0),
    _use("z", "w", ("z", "w"), 100.0),
    _use("w", "y", ("w", "y"), 250.0),
]
_TRIANGLE = [
    _use("a", "b", ("a", "b"), 1.0),
    _use("b", "c", ("b", "c"), 1.0),
    _use("a", "c", ("a", "c"), 1.0),
]
_CHAIN = [
    _use("a", "b", ("a", "b"), 1.0),
    _use("b", "c", ("b", "c"), 1.0),
    _use("c", "d", ("c", "d"), 1.0),
]


def test_a_path_nobody_needs_is_taken_back_out() -> None:
    """The chord buys neither of its ends a way out the ring did not already give it."""
    assert _needed(_RING_PLUS_CHORD, _SQUARE_SITES, 2) == _RING_PLUS_CHORD[:4]


def test_a_path_a_site_would_lose_a_way_out_by_is_kept() -> None:
    """Every ring path is a site's second way out, so the ring survives the judgement whole."""
    assert _needed(_RING_PLUS_CHORD[:4], _SQUARE_SITES, 2) == _RING_PLUS_CHORD[:4]


def test_a_path_whose_loss_would_leave_a_city_carrying_the_network_is_kept() -> None:
    """Dropping one side of a triangle leaves the middle city carrying both other sites.

    Each of the three sites is bought one way out and would still have one without the
    third path, so the ways out alone would let it go. What stops it is that the fiber left
    would fall to the loss of a single city, which the fiber with it does not.
    """
    assert _needed(_TRIANGLE, ("a", "b", "c"), 1) == _TRIANGLE


def test_a_path_whose_loss_would_break_the_backbone_in_two_is_kept() -> None:
    """Dropping the middle of a chain leaves two backbones rather than one.

    Every site is bought one way out and every site still has one on either side of the
    break, so nothing about the ways out refuses this. Being one network is the separate
    thing a backbone owes, and it is what keeps the path.
    """
    assert _needed(_CHAIN, ("a", "b", "c", "d"), 1) == _CHAIN


def test_a_synthesis_that_never_survived_a_city_loss_is_not_held_to_surviving_one() -> None:
    """A chain cannot survive any city's loss, so that cannot be a reason to keep a path.

    Read the other way round, this is what keeps the judgement honest on the fiber a site
    behind a single point of failure really has: a synthesis that never survived a city's loss
    is not made to keep a path on the pretence that it did.
    """
    doubled = [*_CHAIN, _use("a", "b", ("a", "b"), 9.0)]
    assert _needed(doubled, ("a", "b", "c", "d"), 1) == _CHAIN


# A square of hundred-mile segments whose two sides out of ``w`` belong to one carrier and
# whose two sides into ``y`` belong to another, so ``w`` and ``y`` are two hops apart both
# ways round and neither way is one company's to sell.
_SPLIT_SQUARE = fixtures.carrier_fiber_segments({
    ("w", "x"): (100.0, ("lumen",)),
    ("x", "y"): (100.0, ("zayo",)),
    ("w", "z"): (100.0, ("lumen",)),
    ("z", "y"): (100.0, ("zayo",)),
})
# The same square with each way round wholly one company's.
_WHOLE_SQUARE = fixtures.carrier_fiber_segments({
    ("w", "x"): (100.0, ("lumen",)),
    ("x", "y"): (100.0, ("lumen",)),
    ("w", "z"): (100.0, ("zayo",)),
    ("z", "y"): (100.0, ("zayo",)),
})
_PIN_WY = BackboneConstraints(
    number_of_diverse_paths=2, forced_pairs=frozenset({link_key("w", "y")}), seat_cap=4,
)


def test_a_pin_no_carrier_can_join_draws_no_path() -> None:
    """Both ways from w to y change hands halfway, so the pin has nobody to buy from."""
    mesh = _drawn(("w", "x", "y", "z"), _SPLIT_SQUARE, _PIN_WY)
    assert not [use for use in mesh.paths if use.reason == LINK_FOR_PIN]


def test_a_pin_one_carrier_can_join_is_drawn_over_that_carriers_fiber() -> None:
    """One way round is wholly Lumen's, so that is the way the pin is drawn."""
    mesh = _drawn(("w", "x", "y", "z"), _WHOLE_SQUARE, _PIN_WY)
    assert [use.path for use in mesh.paths if use.reason == LINK_FOR_PIN] == [
        ("w", "x", "y"),
    ]


def test_a_drawn_path_names_the_carrier_it_is_ordered_from() -> None:
    """Every path the mesh draws over owned fiber names one company to order it from."""
    mesh = _drawn(("w", "x", "y", "z"), _WHOLE_SQUARE, _PIN_WY)
    assert all(use.carrier in ("lumen", "zayo") for use in mesh.paths)
