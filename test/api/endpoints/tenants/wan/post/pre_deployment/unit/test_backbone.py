"""Unit tests for backbone-mesh selection and routing."""

from __future__ import annotations

from collections.abc import Iterable

import fixtures
from synthesizer.input_graph import PhysicalEdge, edge_key
from synthesizer.model import LINK_FOR_SITE_DIVERSITY, LINK_FOR_TARGET, PathUse
from synthesizer.backbone import (
    BackboneConstraints,
    LinkReason,
    augment_physical_resilience,
    backbone_mesh_paths,
    diverse_mesh_routes,
    restore_diverse_paths,
    select_backbone_mesh_pairs,
    within_limit,
)
from synthesizer.ceiling import BackupRouteLimit
from synthesizer.synthesize import all_pairs_shortest
from synthesizer.graphs import (
    build_adjacency,
    connected_components,
    distances_from,
    is_two_edge_connected,
    is_two_vertex_connected,
    path_edge_keys,
)

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from


def test_backbone_mesh_paths_empty_when_nodes_disconnected() -> None:
    """Backbone mesh paths empty when the backbone nodes are disconnected."""
    edges = physical({("a", "b"): 1.0, ("c", "d"): 1.0})
    adjacency = build_adjacency(edges)
    distances, predecessors = all_pairs_shortest(
        [pop("a"), pop("b"), pop("c"), pop("d")], adjacency
    )
    assert not backbone_mesh_paths(("a", "c"), distances, predecessors, edges)


def _symmetric_distances(weights: dict[tuple[str, str], float]) -> dict[str, dict[str, float]]:
    """Build a symmetric all-pairs distance table from undirected pair weights."""
    nodes = {node for pair in weights for node in pair}
    table: dict[str, dict[str, float]] = {node: {node: 0.0} for node in nodes}
    for (left, right), weight in weights.items():
        table[left][right] = weight
        table[right][left] = weight
    return table


# Five fully-connected backbone nodes with distinct finite inter-node distances.
_FIVE_NODE_DISTANCES = _symmetric_distances({
    ("c1", "c2"): 1.0, ("c1", "c3"): 2.0, ("c1", "c4"): 3.0, ("c1", "c5"): 10.0,
    ("c2", "c3"): 4.0, ("c2", "c4"): 5.0, ("c2", "c5"): 6.0,
    ("c3", "c4"): 7.0, ("c3", "c5"): 8.0,
    ("c4", "c5"): 9.0,
})
_FIVE_NODES = ("c1", "c2", "c3", "c4", "c5")


def _backbone(
    removed: frozenset[tuple[str, str]] = frozenset(),
    number_of_diverse_paths: int = 3,
    forced: frozenset[tuple[str, str]] = frozenset(),
    routes: dict[str, list[tuple[str, ...]]] | None = None,
) -> dict[tuple[str, str], LinkReason]:
    """The five-node backbone wiring each node to its nearest peers."""
    return select_backbone_mesh_pairs(
        _FIVE_NODES,
        _FIVE_NODE_DISTANCES,
        BackboneConstraints(removed, number_of_diverse_paths, forced, routes or {}),
    )


def _node_degrees(pairs: Iterable[tuple[str, str]]) -> dict[str, int]:
    """Distinct-neighbor degree of every five-node vertex over ``pairs``."""
    degrees = {node: 0 for node in _FIVE_NODES}
    for left, right in pairs:
        degrees[left] += 1
        degrees[right] += 1
    return degrees


def test_every_node_meets_its_number_of_diverse_paths() -> None:
    """With three diverse paths asked for, every node wires to at least three others."""
    assert min(_node_degrees(_backbone()).values()) == 3


def test_number_of_diverse_paths_scales_with_the_config() -> None:
    """Lowering the degree to two leaves the least-connected node with two links."""
    assert min(_node_degrees(_backbone(number_of_diverse_paths=2)).values()) == 2


def test_a_node_wires_to_its_nearest_not_its_farthest() -> None:
    """c1's three nearest are c2/c3/c4, so it never wires the distant c5."""
    assert edge_key("c1", "c5") not in _backbone()


def test_each_node_picks_exactly_its_degree_unioned() -> None:
    """Three picks per node union to nine distinct mesh links."""
    assert len(_backbone()) == 9


def test_a_node_picked_by_a_farther_peer_gains_an_extra_link() -> None:
    """c2 is among others' nearest, so it ends one over the three-link target."""
    assert _node_degrees(_backbone())["c2"] == 4


# c5 is the farthest node from everything, so at a target of two nobody else picks it and
# its own picks are the whole of its wiring. That makes it the one node on this fixture
# whose link count is its target and nothing else, which is what the next two tests need.
def test_a_node_with_headroom_takes_only_what_was_asked_for() -> None:
    """c5's fiber reaches four peers and the tenant asked for two, so it wires two.

    This is the decision the ceiling behaviour used to make the other way. A site with
    headroom was aimed at its ceiling on the reasoning that the extra paths were nearly
    free, which is true of the fiber and false of the circuits riding it.
    """
    assert _node_degrees(_backbone(number_of_diverse_paths=2))["c5"] == 2


def test_a_link_a_node_reached_for_is_attributed_to_that_node() -> None:
    """c5's own links name c5 as the site that asked for them."""
    backbone = _backbone(number_of_diverse_paths=2)
    assert backbone[edge_key("c2", "c5")] == LinkReason(LINK_FOR_TARGET, ("c5",))


def test_a_removed_pair_gets_no_link() -> None:
    """An operator-pruned backbone-backbone pair gets no mesh link."""
    assert edge_key("c1", "c2") not in _backbone(frozenset({edge_key("c1", "c2")}))


def test_a_removed_pair_is_filled_by_the_next_nearest() -> None:
    """Dropping c1-c2 makes c1 wire to c5, its next-nearest reachable node."""
    assert edge_key("c1", "c5") in _backbone(frozenset({edge_key("c1", "c2")}))


# c1-c5 is the farthest pair in the table, so a nearest-neighbour mesh never picks it:
# whatever the forced case asserts is the pin at work, not an emergent choice.
_FORCED = frozenset({edge_key("c1", "c5")})


def test_a_forced_pair_gets_a_mesh_link() -> None:
    """An operator-forced backbone-backbone pair is wired even though it is the farthest."""
    assert edge_key("c1", "c5") in _backbone(forced=_FORCED)


def test_a_forced_link_counts_towards_the_number_of_diverse_paths() -> None:
    """c5's forced link fills one of its three slots rather than adding a fourth."""
    assert _node_degrees(_backbone(forced=_FORCED))["c5"] == 3


def test_a_forced_link_displaces_the_farthest_pick() -> None:
    """c5 spends a slot on the forced c1, so it drops c4, the farthest it would have picked."""
    assert edge_key("c4", "c5") not in _backbone(forced=_FORCED)


# Removing three of c1's four peers leaves it only c5, one link below the target of
# three; the backbone must still render rather than collapsing to nothing.
_THINNED = frozenset({edge_key("c1", "c2"), edge_key("c1", "c3"), edge_key("c1", "c4")})


def test_a_node_thinned_below_target_still_renders_a_backbone() -> None:
    """Thinning one node below its diverse path count does not blank the whole backbone."""
    assert _backbone(_THINNED)


def test_a_node_thinned_below_target_keeps_its_one_remaining_link() -> None:
    """The thinned node keeps the single link it can still make."""
    assert _node_degrees(_backbone(_THINNED))["c1"] == 1


def test_a_node_thinned_below_target_wires_to_its_one_reachable_peer() -> None:
    """That single link goes to c5, the only peer c1 has left."""
    assert edge_key("c1", "c5") in _backbone(_THINNED)


def test_a_thinned_backbone_never_re_adds_a_removed_pair() -> None:
    """No removed pair sneaks back into the rendered backbone."""
    assert not _THINNED & set(_backbone(_THINNED))


def test_backbone_wires_what_it_can_when_a_node_is_unreachable() -> None:
    """An unreachable node blanks only its own links, not the whole backbone."""
    distances = _symmetric_distances({("c1", "c2"): 1.0})
    distances["c3"] = {"c3": 0.0}
    assert sorted(select_backbone_mesh_pairs(("c1", "c2", "c3"), distances)) == [
        edge_key("c1", "c2")
    ]


# Two tight triangles -- {a1,a2,a3} and {b1,b2,b3} -- joined only by long but finite
# cross links. A nearest-neighbour mesh of degree two keeps every node wired inside its
# own triangle, so without a connectivity step the two clusters never link. Every cross
# distance is its endpoints' distance to a1/b1 plus the 100-mile crossing, so the table
# is a metric a real carrier graph could produce: the join is genuinely a chokepoint
# rather than a table that lets one node cross more cheaply than its neighbour can.
_TWO_CLUSTER_DISTANCES = _symmetric_distances({
    ("a1", "a2"): 1.0, ("a1", "a3"): 2.0, ("a2", "a3"): 3.0,
    ("b1", "b2"): 1.0, ("b1", "b3"): 2.0, ("b2", "b3"): 3.0,
    ("a1", "b1"): 100.0, ("a1", "b2"): 101.0, ("a1", "b3"): 102.0,
    ("a2", "b1"): 101.0, ("a2", "b2"): 102.0, ("a2", "b3"): 103.0,
    ("a3", "b1"): 102.0, ("a3", "b2"): 103.0, ("a3", "b3"): 104.0,
})
_TWO_CLUSTER_NODES = ("a1", "a2", "a3", "b1", "b2", "b3")


def _two_cluster_mesh(
    removed: frozenset[tuple[str, str]] = frozenset(),
) -> dict[tuple[str, str], LinkReason]:
    """The two-cluster backbone wired at two diverse paths."""
    return select_backbone_mesh_pairs(
        _TWO_CLUSTER_NODES,
        _TWO_CLUSTER_DISTANCES,
        BackboneConstraints(removed, number_of_diverse_paths=2),
    )


def test_two_clusters_are_joined_into_one_component() -> None:
    """Two nearest-neighbour clusters are stitched into a single connected mesh."""
    pairs = _two_cluster_mesh()
    assert len(connected_components(set(_TWO_CLUSTER_NODES), set(pairs))) == 1


def test_two_clusters_are_joined_redundantly() -> None:
    """The stitched backbone survives the loss of any single link (2-edge-connected)."""
    pairs = _two_cluster_mesh()
    assert is_two_edge_connected(set(_TWO_CLUSTER_NODES), set(pairs))


def test_the_cluster_join_uses_the_shortest_cross_link() -> None:
    """The clusters are stitched starting from the shortest cross pair, a1-b1."""
    assert edge_key("a1", "b1") in _two_cluster_mesh()


def test_the_cluster_join_skips_a_removed_cross_pair() -> None:
    """A pruned cross pair is never used to stitch the clusters."""
    removed = frozenset({edge_key("a1", "b1")})
    assert edge_key("a1", "b1") not in _two_cluster_mesh(removed)


def test_the_cluster_join_falls_back_to_the_next_shortest_cross_pair() -> None:
    """With the shortest cross pair pruned, the next shortest stitches the clusters."""
    removed = frozenset({edge_key("a1", "b1")})
    assert edge_key("a1", "b2") in _two_cluster_mesh(removed)


# A backbone whose peers are not all diverse. d hangs off a and e off b, so h reaches
# either one only by transiting a peer it has already picked; f sits on a span of its
# own, two and a half miles out, and shares transit with nobody. h's third-nearest peer
# is therefore d at two miles, reachable only through a, while the diverse f is farther.
_TRANSIT_EDGES = physical({
    ("h", "a"): 1.0, ("h", "b"): 1.0, ("a", "b"): 1.0,
    ("a", "d"): 1.0, ("b", "e"): 1.0, ("d", "e"): 1.0,
    ("h", "f"): 2.5,
})
_TRANSIT_NODES = ("h", "a", "b", "d", "e", "f")
_TRANSIT_DISTANCES = all_pairs_shortest(
    [pop(node) for node in _TRANSIT_NODES], build_adjacency(_TRANSIT_EDGES)
)[0]


def _transit_mesh(
    forced: frozenset[tuple[str, str]] = frozenset(),
) -> dict[tuple[str, str], LinkReason]:
    """The transit backbone wired at three diverse paths."""
    return select_backbone_mesh_pairs(
        _TRANSIT_NODES, _TRANSIT_DISTANCES, BackboneConstraints(frozenset(), 3, forced)
    )


def _peers(pairs: Iterable[tuple[str, str]], node: str) -> set[str]:
    """Every node ``node`` shares a mesh link with."""
    return {other for pair in pairs if node in pair for other in pair if other != node}


def test_a_peer_reachable_only_through_a_nearer_peer_is_skipped() -> None:
    """h skips d, whose shortest path transits a, the peer h picked first."""
    assert edge_key("h", "d") not in _transit_mesh()


def test_the_skipped_slot_goes_to_a_diverse_peer() -> None:
    """h spends the freed slot on the farther f, which shares no transit."""
    assert _peers(_transit_mesh(), "h") == {"a", "b", "f"}


def test_a_node_with_no_diverse_peer_left_still_meets_its_degree() -> None:
    """f leaves the backbone only through h, yet still wires its three links."""
    assert len(_peers(_transit_mesh(), "f")) == 3


def test_a_pinned_peer_counts_when_judging_diversity() -> None:
    """A pinned a still makes d a transit of a peer h holds, so d is skipped."""
    assert edge_key("h", "d") not in _transit_mesh(frozenset({edge_key("h", "a")}))


def test_a_forced_pair_is_wired_even_when_it_shares_transit() -> None:
    """An operator's pin is wired even though its path transits another peer."""
    assert edge_key("h", "d") in _transit_mesh(frozenset({edge_key("h", "d")}))


def test_a_node_short_of_diverse_peers_still_backfills_to_its_target() -> None:
    """d reaches only a and e diversely, and still spends its third slot on b.

    Falling short of diverse peers is not a reason to leave a slot empty: the tenant asked
    for three links and a chokepoint link is worth having up to that number. What the
    backfill will not do is carry on past it.
    """
    assert edge_key("d", "b") in _transit_mesh()


# c5 is the farthest node from every other, so distance alone never reaches for it. A proof
# that c1 has an independent route to c5 is the only thing that would wire the pair, which
# is what makes it the case that tells a proven pick apart from a near one.
_PROVED_TO_THE_FARTHEST: dict[str, list[tuple[str, ...]]] = {"c1": [("c1", "c5")]}
# The same from c5's side, where c5's one proved route is to the node it is farthest from.
_PROVED_FROM_THE_FARTHEST: dict[str, list[tuple[str, ...]]] = {"c5": [("c5", "c1")]}


def test_a_proven_peer_is_picked_over_the_nearer_ones_distance_would_take() -> None:
    """c1 wires the peer its proof reaches, though four others sit closer to it."""
    assert edge_key("c1", "c5") in _backbone(routes=_PROVED_TO_THE_FARTHEST)


def test_a_proof_shorter_than_the_floor_is_backfilled_by_distance() -> None:
    """c5's one proved route leaves it two links short, and its nearest peers make them up."""
    assert _node_degrees(_backbone(routes=_PROVED_FROM_THE_FARTHEST))["c5"] == 3


def test_the_backfill_stops_at_the_floor_rather_than_filling_every_slot() -> None:
    """c5 owes three links and its proof plus two nearest are three, so c4 is never reached."""
    assert edge_key("c4", "c5") not in _backbone(routes=_PROVED_FROM_THE_FARTHEST)


def test_a_node_with_no_proof_of_its_own_is_still_picked_by_distance() -> None:
    """A proof for one node says nothing about another, which wires as it always did."""
    assert edge_key("c1", "c2") in _backbone(routes=_PROVED_FROM_THE_FARTHEST)


def test_a_proved_route_to_a_pruned_peer_is_not_wired() -> None:
    """The fiber can carry the link and the operator has said not to, so it is not wired."""
    pruned = frozenset({edge_key("c1", "c5")})
    assert edge_key("c1", "c5") not in _backbone(pruned, routes=_PROVED_TO_THE_FARTHEST)


_UNIT_MESH_EDGES = physical({
    ("c1", "c2"): 1.0, ("c1", "c3"): 1.0, ("c1", "c4"): 1.0, ("c1", "c5"): 1.0,
    ("c2", "c3"): 1.0, ("c2", "c4"): 1.0, ("c2", "c5"): 1.0,
    ("c3", "c4"): 1.0, ("c3", "c5"): 1.0, ("c4", "c5"): 1.0,
})


def _five_node_mesh_paths(removed: frozenset[tuple[str, str]] = frozenset()) -> list[PathUse]:
    """Route the five-node backbone over a unit-weight physical graph."""
    adjacency = build_adjacency(_UNIT_MESH_EDGES)
    distances, predecessors = all_pairs_shortest([pop(c) for c in _FIVE_NODES], adjacency)
    return backbone_mesh_paths(
        _FIVE_NODES, distances, predecessors, _UNIT_MESH_EDGES, BackboneConstraints(removed)
    )


def test_backbone_mesh_paths_stop_at_the_number_asked_for() -> None:
    """A five-node clique offers each site four diverse paths; three were asked for.

    This test used to assert all ten pairs were wired, which is a full mesh on a network
    that asked for a fraction of one, written down as correct. Each site now picks three
    peers and the union is nine: every span on a unit clique is the same length, so the
    tie falls to the lowest ids and both c4 and c5 pick c1, c2 and c3, leaving the pair
    between them the one nobody reached for.
    """
    assert len(_five_node_mesh_paths()) == 9


def test_backbone_mesh_paths_are_labelled_backbone_mesh() -> None:
    """Every routed backbone path carries the backbone_mesh purpose."""
    assert all(use.purpose == "backbone_mesh" for use in _five_node_mesh_paths())


def test_backbone_mesh_paths_wire_around_a_node_the_substrate_does_not_carry() -> None:
    """A node no fiber mentions has no routes to prove and no links, and the rest still wire."""
    edges = physical({("a", "b"): 1.0})
    adjacency = build_adjacency(edges)
    distances, predecessors = all_pairs_shortest([pop("a"), pop("b"), pop("z")], adjacency)
    uses = backbone_mesh_paths(("a", "b", "z"), distances, predecessors, edges)
    assert {edge_key(use.source, use.target) for use in uses} == {edge_key("a", "b")}


def test_backbone_mesh_paths_omit_a_removed_pair() -> None:
    """An operator-pruned pair gets no routed backbone-mesh path."""
    routed = _five_node_mesh_paths(frozenset({edge_key("c1", "c2")}))
    assert edge_key("c1", "c2") not in {edge_key(use.source, use.target) for use in routed}


# A three-node backbone (a, b, c) whose base mesh routes a-b and b-c both through the
# transit hub h, so h is a single city whose loss strands a node. The carrier graph also
# offers direct a-b, a-c, b-c spans, the alternates a detour can use to route around h.
_HUB_EDGES = physical({
    ("a", "h"): 1.0, ("b", "h"): 1.0, ("c", "h"): 1.0,
    ("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0,
})
_HUB_ONLY = physical({("a", "h"): 1.0, ("b", "h"): 1.0, ("c", "h"): 1.0})
_BASE_HUB = [
    PathUse("backbone_mesh", "a", "b", ("a", "h", "b"), 2.0),
    PathUse("backbone_mesh", "b", "c", ("b", "h", "c"), 2.0),
]


def _augmented_spans(
    base: list[PathUse],
    backbone_ids: tuple[str, ...],
    edges: dict[tuple[str, str], PhysicalEdge],
    removed: frozenset[tuple[str, str]] = frozenset(),
) -> set[tuple[str, str]]:
    """The physical spans the augmented backbone rides over."""
    spans: set[tuple[str, str]] = set()
    for use in augment_physical_resilience(
        base, backbone_ids, edges, BackboneConstraints(removed)
    ):
        spans |= path_edge_keys(use.path)
    return spans


def test_augment_physical_resilience_makes_a_cut_city_survivable() -> None:
    """Detours are added around the shared hub until the fiber survives any city loss."""
    spans = _augmented_spans(_BASE_HUB, ("a", "b", "c"), _HUB_EDGES)
    assert is_two_vertex_connected({vertex for span in spans for vertex in span}, spans)


def test_augment_physical_resilience_stops_when_no_detour_exists() -> None:
    """A hub-only carrier graph offers no city-avoiding alternate, so the base is left as is."""
    assert augment_physical_resilience(
        _BASE_HUB, ("a", "b", "c"), _HUB_ONLY
    ) == _BASE_HUB


def test_augment_physical_resilience_skips_pruned_detour_pairs() -> None:
    """When every backbone cross pair is operator-pruned, no detour is added."""
    pruned = frozenset({edge_key("a", "b"), edge_key("a", "c"), edge_key("b", "c")})
    assert augment_physical_resilience(
        _BASE_HUB, ("a", "b", "c"), _HUB_EDGES, BackboneConstraints(pruned)
    ) == _BASE_HUB


# The same hub, with the alternates moved a thousand miles offshore: the only way around
# ``h`` is out through ``x`` and back. The detour exists and relieves the cut city, and no
# operator would buy a two-thousand-mile protect path for a two-mile link.
_OFFSHORE_EDGES = physical({
    ("a", "h"): 1.0, ("b", "h"): 1.0, ("c", "h"): 1.0,
    ("a", "x"): 1000.0, ("b", "x"): 1000.0, ("c", "x"): 1000.0,
})
_OFFSHORE_LIMIT = BackupRouteLimit(
    3.0, distances_from(build_adjacency(_OFFSHORE_EDGES), ("a", "b", "c"))
)


def test_a_detour_beyond_the_bound_is_not_added() -> None:
    """The cut city stands rather than being relieved by a route nobody would buy."""
    assert augment_physical_resilience(
        _BASE_HUB, ("a", "b", "c"), _OFFSHORE_EDGES,
        BackboneConstraints(limit=_OFFSHORE_LIMIT),
    ) == _BASE_HUB


def test_a_detour_inside_the_bound_is_still_added() -> None:
    """The bound refuses a detour for its length, not for being a detour."""
    limit = BackupRouteLimit(3.0, distances_from(build_adjacency(_HUB_EDGES), ("a", "b", "c")))
    assert augment_physical_resilience(
        _BASE_HUB, ("a", "b", "c"), _HUB_EDGES, BackboneConstraints(limit=limit)
    ) != _BASE_HUB


# One pair, one route drawn through the hub ``h``, and a second way round through ``x`` that
# the pass would take if nothing held it back. The cap is counted per pair, so this is the
# fixture that shows it: the only pair there is is the one already at its number.
_ONE_PAIR_EDGES = physical({
    ("a", "h"): 1.0, ("h", "b"): 1.0, ("a", "x"): 2.0, ("x", "b"): 2.0,
})
_BASE_ONE_PAIR = [PathUse("backbone_mesh", "a", "b", ("a", "h", "b"), 2.0)]


def test_no_detour_is_added_to_a_pair_already_holding_the_paths_it_asked_for() -> None:
    """A pair given its number is protected by the routes it has, whatever cities they leave cut.

    Each detour relieves one city and rides the same fiber for the rest of the way, so an
    unbounded pass buys one route per chokepoint: Ashburn, VA to Salt Lake City, UT crosses
    eight and took four extra routes for them (GitHub issue #58). Here the pair holds the
    one route it asked for, so ``h`` stands and validation is what reports it.
    """
    assert augment_physical_resilience(
        _BASE_ONE_PAIR, ("a", "b"), _ONE_PAIR_EDGES,
        BackboneConstraints(number_of_diverse_paths=1),
    ) == _BASE_ONE_PAIR


def test_a_detour_is_still_added_to_a_pair_with_a_path_left_to_spend() -> None:
    """The cap refuses a route for being one too many, not for being a detour."""
    assert augment_physical_resilience(
        _BASE_ONE_PAIR, ("a", "b"), _ONE_PAIR_EDGES,
        BackboneConstraints(number_of_diverse_paths=2),
    ) != _BASE_ONE_PAIR


# The hub triangle with all three of its pairs drawn, one route each. Every pair the loss of
# ``h`` separates is joined already, so the pass has nowhere left to put a detour: the cities
# it could route around are the cities it may not buy a second circuit to reach.
_BASE_TRIANGLE = [*_BASE_HUB, PathUse("backbone_mesh", "a", "c", ("a", "c"), 1.0)]


def test_no_detour_is_added_where_every_separated_pair_is_joined_already() -> None:
    """``h`` stands as a cut city and is reported, rather than bought off with a circuit.

    Three sites and two paths asked for is one route a pair, so a-b and b-c are both closed
    to the pass and a-c is not separated by ``h`` at all. What the design cannot survive is
    then what ``synthesizer.validation`` says it cannot survive (GitHub issue #59).
    """
    assert augment_physical_resilience(
        _BASE_TRIANGLE, ("a", "b", "c"), _HUB_EDGES,
        BackboneConstraints(number_of_diverse_paths=2, seat_cap=3),
    ) == _BASE_TRIANGLE


# Two sites and nothing else, joined two ways round that share no city. This is Two-Node in
# miniature: one peer apiece, so a tenant asking for two paths is answered by two routes
# over the one pair rather than by links to two peers.
_TWO_SITE_EDGES = physical({
    ("a", "north"): 1.0, ("north", "b"): 1.0,
    ("a", "south"): 2.0, ("south", "b"): 2.0,
    ("a", "long"): 9.0, ("long", "b"): 9.0,
})


def _two_site_paths(number_of_diverse_paths: int, seat_cap: int = 2) -> list[PathUse]:
    """Route the two-site backbone over fiber that joins it three disjoint ways."""
    adjacency = build_adjacency(_TWO_SITE_EDGES)
    distances, predecessors = all_pairs_shortest([pop("a"), pop("b")], adjacency)
    return backbone_mesh_paths(
        ("a", "b"), distances, predecessors, _TWO_SITE_EDGES,
        BackboneConstraints(
            number_of_diverse_paths=number_of_diverse_paths, seat_cap=seat_cap
        ),
    )


def test_a_two_site_backbone_is_drawn_with_the_paths_it_asked_for() -> None:
    """Two asked for over fiber offering three, so two routes are built and the third is not."""
    assert len(_two_site_paths(2)) == 2


def test_a_two_site_backbone_takes_the_shortest_of_the_routes_open_to_it() -> None:
    """The nine-mile way round is the one left unbuilt, not either of the shorter two."""
    assert sorted(use.path[1] for use in _two_site_paths(2)) == ["north", "south"]


def test_a_two_site_backbone_needs_no_detour_once_its_paths_are_drawn() -> None:
    """Two routes sharing no city already survive any one city's loss, so nothing is repaired."""
    assert [use.reason for use in _two_site_paths(2)] == [LINK_FOR_TARGET, LINK_FOR_TARGET]


def test_a_backbone_seated_below_its_cap_is_still_drawn_one_path_a_pair() -> None:
    """Two sites seated where the config allows six is a design short of sites, not of paths.

    The seats the tenant allows are what say whether a site has other peers to reach, and a
    tenant that allows six has bought a network where it does. A run that seats two of them
    is a coverage question; joining the two it seated twice answers a different one nobody
    asked (GitHub issue #59).
    """
    assert len(_two_site_paths(2, seat_cap=6)) == 1


# Two backbone sites a short hop apart through ``m``, plus a thousand-mile pair of spans
# through ``x`` that clears it. Both sites reach ``s`` through ``m`` and nowhere else, so
# routing that link first is what leaves each of them already riding ``m`` when the p-q
# link comes to be routed and the crossing is the only route clear of it. It is four
# hundred times the direct one.
_OFFSHORE_CLEAR = physical({
    ("p", "m"): 1.0, ("m", "q"): 1.0, ("m", "s"): 1.0,
    ("p", "x"): 1000.0, ("x", "q"): 1000.0,
})
_OFFSHORE_CLEAR_ADJACENCY = build_adjacency(_OFFSHORE_CLEAR)
_OFFSHORE_CLEAR_DISTANCES = all_pairs_shortest(
    [pop(node) for node in ("p", "q", "m", "s", "x")], _OFFSHORE_CLEAR_ADJACENCY
)


def _clear_route(limit: BackupRouteLimit | None) -> tuple[str, ...]:
    """The route the mesh lays p-q when both ends already carry ``m``."""
    routes = diverse_mesh_routes(
        [("p", "s"), ("q", "s"), ("p", "q")],
        ("p", "q", "s"),
        _OFFSHORE_CLEAR_DISTANCES[1],
        _OFFSHORE_CLEAR_ADJACENCY,
        BackboneConstraints(limit=limit),
    )
    return next(path for left, right, path in routes if (left, right) == ("p", "q"))


def test_a_clearing_route_beyond_the_bound_falls_back_to_the_shortest_path() -> None:
    """p-q takes the two-mile route through m rather than the two-thousand-mile one."""
    assert _clear_route(
        BackupRouteLimit(3.0, distances_from(_OFFSHORE_CLEAR_ADJACENCY, ("p", "q")))
    ) == ("p", "m", "q")


def test_an_unbounded_clearing_route_still_takes_the_detour() -> None:
    """Without a bound the heuristic buys the crossing, which is the defect it had."""
    assert _clear_route(None) == ("p", "x", "q")


def test_a_pair_the_fiber_cannot_join_has_no_bound_to_break() -> None:
    """Two sites with no working path between them are not measured against one.

    The bound says a protect path may not run far past the working path the link already
    has. Where the fiber joins the two ends nowhere there is no such path, so there is no
    distance to multiply and nothing the bound can say -- and saying nothing is the honest
    answer rather than refusing every route on a measurement that does not exist.
    """
    islands = build_adjacency(physical({("a", "b"): 1.0, ("c", "d"): 1.0}))
    limit = BackupRouteLimit(3.0, distances_from(islands, ("a", "c")))
    assert within_limit(("a", "b", "c"), "a", "c", 500.0, limit)


# h reaches both p and q through g on the cheap side, and q again through r the long way
# round. Routing each link on its own shortest path would send both of h's links through
# g, so one city's loss would take both.
_SHARED_EGRESS_EDGES = physical({
    ("h", "g"): 1.0, ("g", "p"): 1.0, ("g", "q"): 1.0,
    ("h", "r"): 1.0, ("r", "q"): 5.0,
})
# The same fiber with the long way round missing, so q is reachable only through g.
_ONLY_EGRESS_EDGES = physical({
    ("h", "g"): 1.0, ("g", "p"): 1.0, ("g", "q"): 1.0, ("h", "r"): 1.0,
})


def _routed(
    pairs: list[tuple[str, str]],
    edges: dict[tuple[str, str], PhysicalEdge],
    proven: dict[str, list[tuple[str, ...]]] | None = None,
    seat_cap: int | None = None,
) -> list[tuple[str, str, tuple[str, ...]]]:
    """Route the given mesh pairs over ``edges``, along ``proven`` wherever it covers one.

    The backbone is the sites the pairs name, and ``seat_cap`` is the seats the operator
    allows, which is what decides how many routes one pair is drawn with.
    """
    adjacency = build_adjacency(edges)
    ids = {vertex_id for pair in edges for vertex_id in pair}
    _distances, predecessors = all_pairs_shortest([pop(i) for i in sorted(ids)], adjacency)
    return diverse_mesh_routes(
        pairs,
        tuple(sorted({site for pair in pairs for site in pair})),
        predecessors,
        adjacency,
        BackboneConstraints(routes=proven or {}, seat_cap=seat_cap),
    )


def _routes(
    routed: list[tuple[str, str, tuple[str, ...]]]
) -> dict[tuple[str, str], tuple[str, ...]]:
    """The routed links of :func:`_routed`, keyed by the pair each one routes."""
    return {(left, right): path for left, right, path in routed}


def test_the_first_link_of_a_node_takes_its_shortest_path() -> None:
    """With nothing yet to route clear of, a link takes the cheapest path it has."""
    routes = _routes(_routed([("h", "p"), ("h", "q")], _SHARED_EGRESS_EDGES))
    assert routes[("h", "p")] == ("h", "g", "p")


def test_a_second_link_routes_clear_of_the_first_links_transit_city() -> None:
    """h's second link takes the long way round rather than cross g a second time."""
    routes = _routes(_routed([("h", "p"), ("h", "q")], _SHARED_EGRESS_EDGES))
    assert routes[("h", "q")] == ("h", "r", "q")


def test_a_link_with_no_clear_route_falls_back_to_its_shortest_path() -> None:
    """Where the fiber offers no alternative the link is still wired, through g."""
    routes = _routes(_routed([("h", "p"), ("h", "q")], _ONLY_EGRESS_EDGES))
    assert routes[("h", "q")] == ("h", "g", "q")


# m reaches a through c and r, and t reaches a directly, so the m-t link can clear
# neither end at once: every route to m crosses r, and the cheap route to t crosses a.
# Going by way of j gives up on m's cities and keeps t's two links independent.
_ONE_SIDED_EDGES = physical({
    ("t", "a"): 1.0, ("a", "c"): 1.0, ("c", "r"): 1.0, ("r", "m"): 1.0,
    ("t", "j"): 1.0, ("j", "c"): 1.0,
})


def test_a_link_clears_one_end_when_it_cannot_clear_both() -> None:
    """Unable to clear m's cities, the link still clears t's rather than crossing them."""
    routes = _routes(_routed([("a", "t"), ("a", "m"), ("m", "t")], _ONE_SIDED_EDGES))
    assert routes[("m", "t")] == ("m", "r", "c", "j", "t")


# x reaches u only through p and y reaches v only through q, so the x-y link can clear
# one end or the other but never both: the route through q clears x's cities, the route
# through p clears y's, and the first is five times cheaper.
_TWO_WAY_EDGES = physical({
    ("x", "p"): 5.0, ("p", "u"): 1.0, ("p", "y"): 5.0,
    ("y", "q"): 1.0, ("q", "v"): 1.0, ("q", "x"): 1.0,
})


def test_the_cheaper_of_two_one_sided_routes_wins() -> None:
    """With one end clearable either way, the link takes the shorter of the two routes."""
    routes = _routes(_routed([("u", "x"), ("v", "y"), ("x", "y")], _TWO_WAY_EDGES))
    assert routes[("x", "y")] == ("x", "q", "y")


def test_links_of_unrelated_nodes_do_not_constrain_each_other() -> None:
    """A city another node's link crosses is no reason to route this one around it."""
    routes = _routes(_routed([("g", "p"), ("h", "q")], _SHARED_EGRESS_EDGES))
    assert routes[("h", "q")] == ("h", "g", "q")


# h reaches q through g on the cheap side, so an unproved h-q link takes that way round.
# A proof that h has a route through r is the only thing that sends the link the long way,
# which is what tells a proved path apart from the one the heuristic would have chosen.
_H_PROVED_THE_LONG_WAY: dict[str, list[tuple[str, ...]]] = {"h": [("h", "r", "q")]}
# The same fiber proved from q's end instead, so the route arrives pointing the other way.
_Q_PROVED_THE_LONG_WAY: dict[str, list[tuple[str, ...]]] = {"q": [("q", "r", "h")]}


def test_a_link_is_wired_along_the_route_its_node_proved() -> None:
    """h proved a way round through r, so its link takes it rather than the cheaper g."""
    routes = _routes(_routed([("h", "q")], _SHARED_EGRESS_EDGES, _H_PROVED_THE_LONG_WAY))
    assert routes[("h", "q")] == ("h", "r", "q")


def test_a_route_proved_from_the_far_end_is_wired_pointing_at_this_one() -> None:
    """The proof belongs to q and the link runs h to q, so the path is turned to match."""
    routes = _routes(_routed([("h", "q")], _SHARED_EGRESS_EDGES, _Q_PROVED_THE_LONG_WAY))
    assert routes[("h", "q")] == ("h", "r", "q")


def test_one_fiber_proved_from_both_ends_is_wired_once() -> None:
    """A path and its reverse are the same cable, so the pair gets a single link."""
    proven: dict[str, list[tuple[str, ...]]] = {**_H_PROVED_THE_LONG_WAY, **_Q_PROVED_THE_LONG_WAY}
    assert len(_routed([("h", "q")], _SHARED_EGRESS_EDGES, proven)) == 1


# The two ends of one pair proved different fiber: h the cheap way through g, q the long
# way round through r. The two are what the tenant's seats decide between -- a backbone
# with peers to spare joins the pair once, and one whose config seats only these two has
# nowhere else to put the second path.
_ENDS_DISAGREE: dict[str, list[tuple[str, ...]]] = {
    "h": [("h", "g", "q")], **_Q_PROVED_THE_LONG_WAY,
}


def test_two_ends_that_proved_different_fiber_are_wired_once() -> None:
    """Two sites that are joined are joined once, however many ways their fiber offers."""
    assert len(_routed([("h", "q")], _SHARED_EGRESS_EDGES, _ENDS_DISAGREE, 6)) == 1


def test_the_shorter_of_the_two_proved_ways_round_is_the_one_wired() -> None:
    """Six miles through r buys the pair nothing the two through g do not, so g is wired."""
    routes = _routes(_routed([("h", "q")], _SHARED_EGRESS_EDGES, _ENDS_DISAGREE, 6))
    assert routes[("h", "q")] == ("h", "g", "q")


def test_both_are_wired_where_the_seats_leave_the_pair_no_other_peer() -> None:
    """Seated for two sites, the paths a tenant buys can only be routes over the one pair."""
    assert len(_routed([("h", "q")], _SHARED_EGRESS_EDGES, _ENDS_DISAGREE, 2)) == 2


def test_a_pair_no_proof_covers_is_still_routed_by_the_heuristic() -> None:
    """A pin or a join has no proof behind it and is wired the way it always was."""
    routes = _routes(_routed([("h", "p")], _SHARED_EGRESS_EDGES, _H_PROVED_THE_LONG_WAY))
    assert routes[("h", "p")] == ("h", "g", "p")


def test_backbone_mesh_paths_route_a_nodes_links_over_distinct_cities() -> None:
    """Routed through backbone_mesh_paths, h's two links still share no city but h."""
    adjacency = build_adjacency(_SHARED_EGRESS_EDGES)
    ids = sorted({vertex_id for pair in _SHARED_EGRESS_EDGES for vertex_id in pair})
    distances, predecessors = all_pairs_shortest([pop(i) for i in ids], adjacency)
    uses = backbone_mesh_paths(
        ("h", "p", "q"), distances, predecessors, _SHARED_EGRESS_EDGES,
        BackboneConstraints(number_of_diverse_paths=2),
    )
    routed = {edge_key(use.source, use.target): set(use.path) - {"h"} for use in uses}
    assert not routed[edge_key("h", "p")] & routed[edge_key("h", "q")]


# Three sites over three shared hub cities, where the two ends of the pair b-c each proved
# their own way to the other (see ``fixtures.SHARED_HUB_SPANS``), and the same three with a
# fourth site joined to two of them over fiber of its own. The pair is what the two graphs
# decide between: with a fourth site to reach, b has a way out that no hub carries and the
# pair is joined once; without one, the second route to c is the only fiber left that fails
# on its own, and joining the pair twice is what the tenant's two paths are buying.
def _shared_hub_paths(
    edges: dict[tuple[str, str], PhysicalEdge], sites: tuple[str, ...]
) -> list[PathUse]:
    """Route one of the two shared-hub backbones, two paths asked of each site."""
    adjacency = build_adjacency(edges)
    ids = sorted({vertex_id for pair in edges for vertex_id in pair})
    distances, predecessors = all_pairs_shortest([pop(i) for i in ids], adjacency)
    return backbone_mesh_paths(
        sites, distances, predecessors, edges,
        BackboneConstraints(number_of_diverse_paths=2, seat_cap=len(sites)),
    )


def _pair_paths(uses: list[PathUse], left: str, right: str) -> list[PathUse]:
    """The routes drawn between one pair of sites, in the order they were drawn."""
    return [
        use for use in uses if edge_key(use.source, use.target) == edge_key(left, right)
    ]


def _peer_backbone() -> list[PathUse]:
    """The four-site backbone, where b reaches d over fiber no hub carries."""
    return _shared_hub_paths(
        fixtures.SHARED_HUB_PEER_EDGES, fixtures.SHARED_HUB_PEER_SITES
    )


def test_a_pair_whose_two_ends_proved_different_fiber_is_drawn_once() -> None:
    """b proved its way to c and c proved its way to b, and the two sites are one pair.

    This is the shape no other fixture here can make. On a unit clique both ends prove the
    same span and the two collapse into one route on their own, so the number a pair is
    held to is never reached (GitHub issue #59).
    """
    assert len(_pair_paths(_peer_backbone(), "b", "c")) == 1


def test_the_route_drawn_for_that_pair_is_the_shorter_of_the_two() -> None:
    """Two hundred miles through h1 rather than five hundred through h3."""
    assert _pair_paths(_peer_backbone(), "b", "c")[0].path == ("b", "h1", "c")


def test_the_four_sites_are_drawn_one_circuit_a_pair() -> None:
    """Five pairs and five circuits: none joined twice, and none left unjoined."""
    assert len(_peer_backbone()) == 5


def _hub_only_backbone() -> list[PathUse]:
    """The three-site backbone, where every way out of every site is one of the three hubs."""
    return _shared_hub_paths(fixtures.SHARED_HUB_EDGES, fixtures.SHARED_HUB_SITES)


def test_a_pair_is_drawn_twice_where_the_fiber_leaves_a_site_nothing_else() -> None:
    """Drawn once, b's links to a and to c both ride h1, and b asked for two ways out.

    Every peer b has is joined to it already, so the second circuit to c is the only thing
    left that a single city's loss does not take with the first. Refusing it would refuse
    the design, which is what the count of routes a pair may hold cannot be allowed to do.
    """
    assert len(_pair_paths(_hub_only_backbone(), "b", "c")) == 2


def test_the_route_put_back_is_the_one_that_site_proved() -> None:
    """b proved its way to c through h3, and that is the way out h1 cannot take with it."""
    assert _pair_paths(_hub_only_backbone(), "b", "c")[-1].path == ("b", "h3", "c")


def test_the_route_put_back_says_what_it_is_there_for() -> None:
    """A second circuit between two sites is not a link b reached for, and says so.

    An operator reading a network larger than the one they asked for is owed the reason
    beside every extra circuit, and this one has its own: the fiber left b no other way out
    (see :data:`synthesizer.model.LINK_FOR_SITE_DIVERSITY`).
    """
    assert _pair_paths(_hub_only_backbone(), "b", "c")[-1].reason == LINK_FOR_SITE_DIVERSITY


# One site whose three links were drawn along fiber it did not prove: ``a`` proved a way out
# through each of h1, h2 and h3, and holds instead a route to b that rides h1 the long way
# round, a route to c through h2 and a route to d that rides h2 as well. So it is short --
# the h2 pair count as one way out -- and the two routes it proved that were not drawn are
# not equally worth putting back. The one to b crosses h1, which the link it already holds
# to b crosses too, so buying it changes nothing a city's loss would take.
_SHORT_SITE_EDGES = physical({
    ("a", "h1"): 1.0, ("h1", "b"): 1.0, ("h1", "x"): 1.0, ("x", "b"): 1.0,
    ("a", "h2"): 1.0, ("h2", "c"): 1.0, ("h2", "y"): 1.0, ("y", "d"): 1.0,
    ("a", "h3"): 5.0, ("h3", "d"): 5.0,
})
_SHORT_SITE_PROVED: dict[str, list[tuple[str, ...]]] = {
    "a": [("a", "h1", "b"), ("a", "h2", "c"), ("a", "h3", "d")],
}
_SHORT_SITE_USES = [
    PathUse("backbone_mesh", "a", "b", ("a", "h1", "x", "b"), 3.0),
    PathUse("backbone_mesh", "a", "c", ("a", "h2", "c"), 2.0),
    PathUse("backbone_mesh", "a", "d", ("a", "h2", "y", "d"), 3.0),
]


def _short_site_restored() -> list[PathUse]:
    """The three links a holds, plus whatever putting a proved route back is worth."""
    return restore_diverse_paths(
        _SHORT_SITE_USES, _SHORT_SITE_EDGES,
        BackboneConstraints(number_of_diverse_paths=3, routes=_SHORT_SITE_PROVED),
    )


def test_a_route_that_would_not_raise_the_count_is_not_put_back() -> None:
    """Two miles through h1 to a peer already reached through h1 buys nothing, so it is not."""
    assert ("a", "h1", "b") not in [use.path for use in _short_site_restored()]


def test_the_route_that_does_raise_the_count_is_put_back_though_it_costs_more() -> None:
    """Ten miles through h3 is five times the other and is the only one that is a way out."""
    assert _short_site_restored()[-1].path == ("a", "h3", "d")
