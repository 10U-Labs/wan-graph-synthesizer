"""Unit tests for backbone-mesh selection and routing."""

from __future__ import annotations

import fixtures
from synthesizer.input_graph import edge_key
from synthesizer.model import PathUse
from synthesizer.backbone import (
    BackboneConstraints,
    backbone_mesh_paths,
    select_backbone_mesh_pairs,
)
from synthesizer.synthesize import all_pairs_shortest
from synthesizer.graphs import build_adjacency, connected_components, is_two_edge_connected

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
    removed: frozenset[tuple[str, str]] = frozenset(), mesh_degree: int = 3
) -> list[tuple[str, str]]:
    """The five-node backbone wiring each node to its nearest peers."""
    return select_backbone_mesh_pairs(
        _FIVE_NODES, _FIVE_NODE_DISTANCES, removed, mesh_degree
    )


def _node_degrees(pairs: list[tuple[str, str]]) -> dict[str, int]:
    """Distinct-neighbor degree of every five-node vertex over ``pairs``."""
    degrees = {node: 0 for node in _FIVE_NODES}
    for left, right in pairs:
        degrees[left] += 1
        degrees[right] += 1
    return degrees


def test_every_node_meets_its_mesh_degree() -> None:
    """With a mesh degree of three, every node wires to at least three others."""
    assert min(_node_degrees(_backbone()).values()) == 3


def test_mesh_degree_scales_with_the_config() -> None:
    """Lowering the degree to two leaves the least-connected node with two links."""
    assert min(_node_degrees(_backbone(mesh_degree=2)).values()) == 2


def test_a_node_wires_to_its_nearest_not_its_farthest() -> None:
    """c1's three nearest are c2/c3/c4, so it never wires the distant c5."""
    assert edge_key("c1", "c5") not in _backbone()


def test_each_node_picks_exactly_its_degree_unioned() -> None:
    """Three picks per node union to nine distinct mesh links."""
    assert len(_backbone()) == 9


def test_a_node_picked_by_a_farther_peer_gains_an_extra_link() -> None:
    """c2 is among others' nearest, so it ends one over the three-link target."""
    assert _node_degrees(_backbone())["c2"] == 4


def test_a_removed_pair_gets_no_link() -> None:
    """An operator-pruned backbone-backbone pair gets no mesh link."""
    assert edge_key("c1", "c2") not in _backbone(frozenset({edge_key("c1", "c2")}))


def test_a_removed_pair_is_filled_by_the_next_nearest() -> None:
    """Dropping c1-c2 makes c1 wire to c5, its next-nearest reachable node."""
    assert edge_key("c1", "c5") in _backbone(frozenset({edge_key("c1", "c2")}))


# Removing three of c1's four peers leaves it only c5, one link below the target of
# three; the backbone must still render rather than collapsing to nothing.
_THINNED = frozenset({edge_key("c1", "c2"), edge_key("c1", "c3"), edge_key("c1", "c4")})


def test_a_node_thinned_below_target_still_renders_a_backbone() -> None:
    """Thinning one node below its mesh degree does not blank the whole backbone."""
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
    assert select_backbone_mesh_pairs(("c1", "c2", "c3"), distances) == [edge_key("c1", "c2")]


# Two tight triangles -- {a1,a2,a3} and {b1,b2,b3} -- joined only by long but finite
# cross links. A nearest-neighbour mesh of degree two keeps every node wired inside its
# own triangle, so without a connectivity step the two clusters never link.
_TWO_CLUSTER_DISTANCES = _symmetric_distances({
    ("a1", "a2"): 1.0, ("a1", "a3"): 2.0, ("a2", "a3"): 3.0,
    ("b1", "b2"): 1.0, ("b1", "b3"): 2.0, ("b2", "b3"): 3.0,
    ("a1", "b1"): 100.0, ("a1", "b2"): 101.0, ("a1", "b3"): 102.0,
    ("a2", "b1"): 103.0, ("a2", "b2"): 104.0, ("a2", "b3"): 105.0,
    ("a3", "b1"): 106.0, ("a3", "b2"): 107.0, ("a3", "b3"): 108.0,
})
_TWO_CLUSTER_NODES = ("a1", "a2", "a3", "b1", "b2", "b3")


def _two_cluster_mesh(
    removed: frozenset[tuple[str, str]] = frozenset(),
) -> list[tuple[str, str]]:
    """The two-cluster backbone wired at mesh degree two."""
    return select_backbone_mesh_pairs(
        _TWO_CLUSTER_NODES, _TWO_CLUSTER_DISTANCES, removed, mesh_degree=2
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


def test_backbone_mesh_paths_route_each_mesh_link() -> None:
    """The backbone routes one path per selected mesh link: nine over five nodes."""
    assert len(_five_node_mesh_paths()) == 9


def test_backbone_mesh_paths_are_labelled_backbone_mesh() -> None:
    """Every routed backbone path carries the backbone_mesh purpose."""
    assert all(use.purpose == "backbone_mesh" for use in _five_node_mesh_paths())


def test_backbone_mesh_paths_omit_a_removed_pair() -> None:
    """An operator-pruned pair gets no routed backbone-mesh path."""
    routed = _five_node_mesh_paths(frozenset({edge_key("c1", "c2")}))
    assert edge_key("c1", "c2") not in {edge_key(use.source, use.target) for use in routed}
