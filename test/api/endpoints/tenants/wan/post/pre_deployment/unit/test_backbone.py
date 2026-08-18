"""Unit tests for the paths a backbone is drawn with over the fiber it was chosen with.

``synthesizer.backbone`` no longer decides anything one pair of sites at a time. The fiber
is chosen for the whole design at once by ``synthesizer.survivable``, each site's ways out
are read off that fiber, and every path nobody needs is taken back out. So the cases here
are about the finished list of paths rather than about the order four passes ran in: which
pairs ended up joined, which fiber each path took, and which paths were dropped again.

Two graphs carry almost all of it. The square is four sites on a ring of hundred-mile
segments with two chords at two hundred and fifty, so the only design that gives every site
two ways out is the ring itself and both the count and the mileage are forced. The
shared-egress graph is the shape GitHub issue #60 is about: the fewest-mile way from ``hub``
to ``q`` runs through ``m``, which is a city ``hub`` already stands on to reach ``p``, and a
slightly longer way through ``n`` does not. A design that decides one pair at a time takes
the shorter way and leaves ``hub`` with one way out; a design that chooses the whole thing
at once takes the longer one.
"""

from __future__ import annotations

import fixtures
from synthesizer.input_graph import PhysicalEdge, edge_key
from synthesizer.model import LINK_FOR_PIN, LINK_FOR_TARGET, DesignPath
from synthesizer.backbone import (
    BackboneConstraints,
    BackboneMesh,
    _needed,
    backbone_mesh,
    path_geometry_miles,
)
from synthesizer.synthesize import all_pairs_shortest
from synthesizer.graphs import build_adjacency

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from


def _drawn(
    sites: tuple[str, ...],
    edges: dict[tuple[str, str], PhysicalEdge],
    constraints: BackboneConstraints,
) -> BackboneMesh:
    """The mesh a whole fiber choice and assembly settles on over one graph."""
    adjacency = build_adjacency(edges)
    cities = sorted({city for pair in edges for city in pair})
    distances, _predecessors = all_pairs_shortest([pop(city) for city in cities], adjacency)
    return backbone_mesh(sites, distances, edges, constraints)


def _pairs(mesh: BackboneMesh) -> set[tuple[str, str]]:
    """Every pair of sites the mesh joined, however many paths it joined them with."""
    return {edge_key(use.source, use.target) for use in mesh.paths}


def _mesh_miles(mesh: BackboneMesh) -> float:
    """The fiber miles every path in the mesh runs on, added up."""
    return sum(use.distance_miles for use in mesh.paths)


def _joining(mesh: BackboneMesh, left: str, right: str) -> DesignPath:
    """The path the mesh drew between one pair of sites."""
    return next(
        use
        for use in mesh.paths
        if edge_key(use.source, use.target) == edge_key(left, right)
    )


# Four sites on a ring of hundred-mile segments, with the two chords priced at two hundred
# and fifty. Every site needs two ways out and has only two fiber directions to find them
# in, so the ring is the whole of the answer: four paths, four hundred miles, and neither
# chord bought. The chords are what make it an answer rather than the only graph there is.
_SQUARE_SITES = ("w", "x", "y", "z")
_SQUARE_EDGES = physical({
    ("w", "x"): 100.0, ("x", "y"): 100.0, ("y", "z"): 100.0, ("z", "w"): 100.0,
    ("w", "y"): 250.0, ("x", "z"): 250.0,
})
_TWO_WAYS_OUT = BackboneConstraints(number_of_diverse_paths=2, seat_cap=4)
_SQUARE = _drawn(_SQUARE_SITES, _SQUARE_EDGES, _TWO_WAYS_OUT)


def test_the_square_is_drawn_with_one_path_a_pair_round_the_ring() -> None:
    """Four sites needing two ways out each are joined round the ring and nowhere else."""
    assert _pairs(_SQUARE) == {
        edge_key("w", "x"), edge_key("x", "y"), edge_key("y", "z"), edge_key("z", "w"),
    }


def test_the_square_buys_neither_of_the_chords() -> None:
    """A chord costs two hundred and fifty miles and buys nobody a way out, so it is not bought.

    The old passes could reach for one: a chord is the shortest way between the two sites it
    joins, and a pass drawing that pair on its own had no way to see that the ring already
    gave both of them everything they were owed.
    """
    assert _SQUARE_EDGES.keys() - {
        edge_key(*pair) for use in _SQUARE.paths for pair in zip(use.path, use.path[1:])
    } == {edge_key("w", "y"), edge_key("x", "z")}


def test_the_square_runs_the_fewest_miles_its_fiber_allows() -> None:
    """Four hundred miles: every site owes two ways out, so four segments is the floor."""
    assert _mesh_miles(_SQUARE) == 400.0


def test_the_square_publishes_the_floor_it_was_judged_against() -> None:
    """The fewest miles any design meeting the same requirements could run is four hundred.

    Each of the four sites needs two ways out, so the segments the design holds add to at
    least four however they are shared out, and the four shortest are the ring.
    """
    assert round(_SQUARE.lower_bound_miles, 3) == 400.0


def test_the_square_runs_no_further_than_twice_the_floor() -> None:
    """The guarantee the whole choice exists for, asserted rather than assumed."""
    assert _mesh_miles(_SQUARE) <= 2 * _SQUARE.lower_bound_miles


def test_every_path_the_square_draws_says_a_site_reached_for_it() -> None:
    """No path is in the design on the tool's own account; each one answers a site's number."""
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
# p-to-q segment closes the ring, so a whole-design choice buys five segments and 52 miles.
_EGRESS_SITES = ("hub", "p", "q")
_EGRESS_EDGES = physical({
    ("hub", "m"): 10.0, ("m", "p"): 10.0, ("m", "q"): 10.0,
    ("hub", "n"): 11.0, ("n", "q"): 11.0, ("p", "q"): 10.0,
})
_EGRESS = _drawn(_EGRESS_SITES, _EGRESS_EDGES, BackboneConstraints(
    number_of_diverse_paths=2, seat_cap=3,
))


def test_the_longer_way_round_a_shared_city_is_the_one_drawn() -> None:
    """hub reaches q through n at twenty-two miles rather than through m at twenty.

    This is the narrowest statement of the defect. The way through ``m`` is shorter and is
    built from a segment hub's path to ``p`` already rides, so taking it would leave one
    city's loss taking both of hub's paths. Deciding the pair on its own cannot see that;
    deciding the whole design can.
    """
    assert ("hub", "n", "q") in {use.path for use in _EGRESS.paths}


def test_the_shorter_way_round_that_shared_city_is_not_bought_at_all() -> None:
    """The m-to-q segment is fiber the finished design never orders."""
    assert edge_key("m", "q") not in {
        edge_key(*pair) for use in _EGRESS.paths for pair in zip(use.path, use.path[1:])
    }


def test_the_shared_egress_graph_joins_all_three_pairs_once() -> None:
    """Three sites, three pairs, one path each: nothing is joined twice and nothing is left out."""
    assert len(_EGRESS.paths) == 3


def test_the_shared_egress_design_runs_the_miles_its_five_segments_cost() -> None:
    """Fifty-two miles, which is the five segments the choice bought read back as paths."""
    assert _mesh_miles(_EGRESS) == 52.0


def test_no_path_the_shared_egress_design_holds_could_be_taken_back_out() -> None:
    """Every one of the three paths is the second way out of one of the three sites."""
    assert _needed(_EGRESS.paths, _EGRESS_SITES, 2) == _EGRESS.paths


# The square again with one pair struck out by the operator, and again with one pinned. A
# pruned pair is a pair no path may end at, and a pinned pair is one that is joined whatever
# the choice of fiber said; the chord is pinned rather than a ring segment because no design
# over this graph reaches for it, so what the pin does cannot be mistaken for what the
# choice would have done anyway.
_PRUNED = _drawn(_SQUARE_SITES, _SQUARE_EDGES, BackboneConstraints(
    removed_pairs=frozenset({edge_key("w", "x")}), number_of_diverse_paths=2, seat_cap=4,
))
_PINNED_CHORD = _drawn(_SQUARE_SITES, _SQUARE_EDGES, BackboneConstraints(
    number_of_diverse_paths=2, forced_pairs=frozenset({edge_key("w", "y")}), seat_cap=4,
))
_PINNED_SEGMENT = _drawn(_SQUARE_SITES, _SQUARE_EDGES, BackboneConstraints(
    number_of_diverse_paths=2, forced_pairs=frozenset({edge_key("w", "x")}), seat_cap=4,
))


def test_a_pruned_pair_is_never_joined_by_a_drawn_path() -> None:
    """The operator struck the pair out, so no site's way out is allowed to end there."""
    assert edge_key("w", "x") not in _pairs(_PRUNED)


def test_a_pruned_pair_leaves_the_rest_of_the_backbone_drawn() -> None:
    """Striking out one pair costs that pair its path and costs the other sites nothing."""
    assert edge_key("y", "z") in _pairs(_PRUNED)


def test_a_pinned_pair_is_joined_however_the_fiber_was_chosen() -> None:
    """No design over this graph reaches for the chord, so the pin is what joins the pair."""
    assert edge_key("w", "y") in _pairs(_PINNED_CHORD)


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


def test_a_pin_over_fiber_the_design_would_have_bought_anyway_is_still_a_pin() -> None:
    """The pinned pair is one the ring joins too, and the pin is what the path is recorded as."""
    assert _joining(_PINNED_SEGMENT, "w", "x").reason == LINK_FOR_PIN


# Two sites the carrier's fiber never joins, pinned together by an operator who was wrong
# about the map. It is the one thing a pin cannot ask for, and the design says so by drawing
# nothing rather than by failing.
_ISLANDS = physical({("a", "b"): 1.0, ("c", "d"): 1.0})
_ISLAND_PIN = _drawn(("a", "c"), _ISLANDS, BackboneConstraints(
    forced_pairs=frozenset({edge_key("a", "c")}),
))


def test_a_backbone_the_fiber_never_joins_is_drawn_with_no_paths() -> None:
    """Two sites on separate fiber have no ways out to draw, pinned to each other or not."""
    assert _ISLAND_PIN.paths == []


def test_a_backbone_the_fiber_never_joins_is_floored_at_nothing() -> None:
    """There is no fiber to choose from, so the fewest miles any design could run is none."""
    assert _ISLAND_PIN.lower_bound_miles == 0.0


def test_a_site_the_fiber_does_not_carry_costs_the_others_nothing() -> None:
    """A site no fiber mentions draws no path, and the two the fiber does carry still join."""
    edges = physical({("a", "b"): 1.0})
    mesh = _drawn(("a", "b", "zed"), edges, BackboneConstraints(number_of_diverse_paths=1))
    assert _pairs(mesh) == {edge_key("a", "b")}


def test_path_geometry_miles_adds_up_the_segments_a_path_crosses() -> None:
    """A path's mileage is the fiber it runs on, segment by segment."""
    assert path_geometry_miles(("w", "x", "y"), _SQUARE_EDGES) == 200.0


# Four hand-built designs the assembly would never produce, each one holding a path that has
# to be judged on a different ground. Written out rather than synthesized because each is a
# design some other fiber choice could hand over, and the test is what the judgement does
# with it rather than how it came to be.
def _use(source: str, target: str, path: tuple[str, ...], miles: float) -> DesignPath:
    """One drawn path between two sites, over the cities named."""
    return DesignPath("backbone_mesh", source, target, path, miles)


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


def test_a_design_that_never_survived_a_city_loss_is_not_held_to_surviving_one() -> None:
    """A chain cannot survive any city's loss, so that cannot be a reason to keep a path.

    Read the other way round, this is what keeps the judgement honest on the fiber a site
    behind a single point of failure really has: a design that never survived a city's loss
    is not made to keep a path on the pretence that it did.
    """
    doubled = [*_CHAIN, _use("a", "b", ("a", "b"), 9.0)]
    assert _needed(doubled, ("a", "b", "c", "d"), 1) == _CHAIN
