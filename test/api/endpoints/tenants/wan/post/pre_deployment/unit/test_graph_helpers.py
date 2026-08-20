"""Unit tests for the pure graph and parsing helpers."""

from __future__ import annotations

import math

import pytest

from synthesizer.graphs import (
    articulation_points,
    biconnected_block_membership,
    bridge_links,
    bridges,
    connected_components,
    dijkstra,
    survives_any_one_site_loss,
    path_link_keys,
    reconstruct_path,
    bridgeless_components,
)
from synthesizer.input_graph import Site, link_key, haversine_miles


def make_site(site_id: str, lat: float, lon: float) -> Site:
    """Test helper: build make site."""
    return Site(id=site_id, name=site_id, kind="PoP", coords=(lat, lon))


def _adjacency(pairs: list[tuple[str, str]]) -> dict[str, list[tuple[str, float]]]:
    """Test helper: a unit-weight undirected adjacency map from site pairs."""
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for left, right in pairs:
        adjacency.setdefault(left, []).append((right, 1.0))
        adjacency.setdefault(right, []).append((left, 1.0))
    return adjacency


# Two triangles -- {a,b,c} and {d,e,f} -- joined only by the single segment c-d, the lone
# bridge between two otherwise bridgeless pockets.
_TWO_POCKETS = _adjacency(
    [("a", "b"), ("b", "c"), ("a", "c"), ("c", "d"), ("d", "e"), ("e", "f"), ("d", "f")]
)

# A bowtie: two triangles -- {a,b,c} and {c,d,e} -- sharing the single cut city c. It has
# no bridge (every segment lies on a triangle), yet c is an articulation point: the lobes
# fall apart when it is removed. The case where surviving any one link's loss and surviving
# any one site's loss diverge.
_BOWTIE = _adjacency(
    [("a", "b"), ("b", "c"), ("a", "c"), ("c", "d"), ("d", "e"), ("c", "e")]
)


def test_link_key_orders_pair() -> None:
    """Link key orders pair."""
    assert link_key("b", "a") == ("a", "b")


def test_link_key_rejects_self_loop() -> None:
    """Link key rejects self loop."""
    with pytest.raises(ValueError):
        link_key("a", "a")


def test_haversine_zero_distance() -> None:
    """Haversine zero distance."""
    site = make_site("x", 40.0, -100.0)
    assert haversine_miles(site, site) == pytest.approx(0.0)


def test_haversine_known_distance() -> None:
    # New York to Los Angeles is roughly 2450 miles.
    """Haversine known distance."""
    new_york = make_site("ny", 40.7128, -74.006)
    los_angeles = make_site("la", 34.0522, -118.2437)
    assert haversine_miles(new_york, los_angeles) == pytest.approx(2450.0, abs=30.0)


def test_dijkstra_distance_along_chain() -> None:
    """Dijkstra distance along chain."""
    adjacency = {"a": [("b", 2.0)], "b": [("a", 2.0), ("c", 3.0)], "c": [("b", 3.0)]}
    distances, _predecessors = dijkstra(adjacency, "a")
    assert distances["c"] == 5.0


def test_reconstruct_path_along_chain() -> None:
    """Reconstruct path along chain."""
    adjacency = {"a": [("b", 2.0)], "b": [("a", 2.0), ("c", 3.0)], "c": [("b", 3.0)]}
    _distances, predecessors = dijkstra(adjacency, "a")
    assert reconstruct_path("a", "c", predecessors) == ("a", "b", "c")


def test_connected_components_counts_islands() -> None:
    """Connected components counts islands."""
    ids = {"a", "b", "c", "d"}
    links = {("a", "b"), ("c", "d")}
    assert len(connected_components(ids, links)) == 2


def test_articulation_point_detected() -> None:
    """Articulation point detected."""
    ids = {"a", "b", "c"}
    links = {("a", "b"), ("b", "c")}
    assert articulation_points(ids, links) == {"b"}


def test_cycle_has_no_articulation_points() -> None:
    """Cycle has no articulation points."""
    ids = {"a", "b", "c"}
    links = {("a", "b"), ("b", "c"), ("a", "c")}
    assert articulation_points(ids, links) == set()


def test_unreachable_target_has_infinite_distance() -> None:
    """Unreachable target has infinite distance."""
    adjacency = {"a": [("b", 1.0)], "b": [("a", 1.0)], "c": []}
    distances, _predecessors = dijkstra(adjacency, "a")
    assert distances.get("c", math.inf) == math.inf


def test_dijkstra_relaxes_past_a_stale_heap_entry() -> None:
    """Dijkstra relaxes past a stale heap entry."""
    adjacency = {
        "a": [("b", 10.0), ("c", 1.0)],
        "b": [("a", 10.0), ("c", 1.0)],
        "c": [("a", 1.0), ("b", 1.0)],
    }
    distances, _predecessors = dijkstra(adjacency, "a")
    assert distances["b"] == 2.0


def test_reconstruct_path_source_equals_target() -> None:
    """Reconstruct path source equals target."""
    assert reconstruct_path("a", "a", {}) == ("a",)


def test_reconstruct_path_unreachable_returns_empty() -> None:
    """Reconstruct path unreachable returns empty."""
    assert not reconstruct_path("a", "z", {})


def test_reconstruct_path_broken_chain_returns_empty() -> None:
    """Reconstruct path broken chain returns empty."""
    assert not reconstruct_path("a", "c", {"c": "b"})


def test_path_link_keys_for_a_three_site_path() -> None:
    """Path link keys for a three site path."""
    assert path_link_keys(("a", "b", "c")) == {link_key("a", "b"), link_key("b", "c")}


def test_dfs_root_with_two_children_is_an_articulation_point() -> None:
    """Dfs root with two children is an articulation point."""
    assert articulation_points({"a", "b", "c"}, {("a", "b"), ("a", "c")}) == {"a"}


def test_connected_components_ignores_external_endpoints() -> None:
    """Connected components ignores external endpoints."""
    components = connected_components({"a", "b"}, {("a", "b"), ("a", "z")})
    assert components == [["a", "b"]]


def test_bridges_names_every_cut_link_in_a_chain() -> None:
    """Every link of a chain is a bridge, since removing it splits the chain."""
    assert bridges({"a", "b", "c"}, {("a", "b"), ("b", "c")}) == {
        link_key("a", "b"),
        link_key("b", "c"),
    }


def test_cycle_has_no_bridges() -> None:
    """A cycle has no bridges: every link lies on a cycle, so none is a cut link."""
    assert bridges({"a", "b", "c"}, {("a", "b"), ("b", "c"), ("a", "c")}) == set()


def test_bridge_links_finds_the_lone_cut_between_two_pockets() -> None:
    """The single segment joining two bridgeless pockets is the only bridge."""
    assert bridge_links(_TWO_POCKETS) == {link_key("c", "d")}


def test_bridge_links_empty_for_a_cycle() -> None:
    """A cycle has no bridge segments; the linear sweep agrees with the probing search."""
    assert bridge_links(_adjacency([("a", "b"), ("b", "c"), ("a", "c")])) == set()


def test_bridgeless_components_labels_a_cycle_as_one() -> None:
    """Every site of a bridgeless cycle shares one bridgeless component."""
    labels = bridgeless_components(_adjacency([("a", "b"), ("b", "c"), ("a", "c")]))
    assert len(set(labels.values())) == 1


def test_bridgeless_components_splits_two_pockets_at_the_bridge() -> None:
    """Two pockets joined by a single segment fall into two components."""
    labels = bridgeless_components(_TWO_POCKETS)
    assert labels["a"] != labels["d"]


def test_bridgeless_components_labels_a_chain_as_singletons() -> None:
    """Every segment of a chain is a bridge, so each site is its own component."""
    labels = bridgeless_components(_adjacency([("a", "b"), ("b", "c")]))
    assert len(set(labels.values())) == 3


def test_dijkstra_paths_around_a_blocked_segment() -> None:
    """Blocking the direct segment forces the detour, lengthening the shortest path."""
    adjacency = _adjacency([("a", "b"), ("b", "c"), ("a", "c")])
    distances, _predecessors = dijkstra(adjacency, "a", frozenset({link_key("a", "c")}))
    assert distances["c"] == 2.0


def test_block_membership_labels_a_cycle_as_one_shared_block() -> None:
    """Every site of a cycle lies on one common biconnected block."""
    blocks = biconnected_block_membership(_adjacency([("a", "b"), ("b", "c"), ("a", "c")]))
    assert blocks["a"] == blocks["b"] == blocks["c"] != frozenset()


def test_block_membership_splits_two_pockets() -> None:
    """Sites in different pockets share no biconnected block."""
    blocks = biconnected_block_membership(_TWO_POCKETS)
    assert not blocks["a"] & blocks["d"]


def test_block_membership_gives_a_bridge_no_block() -> None:
    """A bridge is no cyclic block, so its two endpoints share none."""
    blocks = biconnected_block_membership(_TWO_POCKETS)
    assert not blocks["c"] & blocks["d"]


def test_block_membership_labels_a_chain_as_blockless() -> None:
    """Every segment of a chain is a bridge, so no site sits in any block."""
    blocks = biconnected_block_membership(_adjacency([("a", "b"), ("b", "c")]))
    assert blocks == {"a": frozenset(), "b": frozenset(), "c": frozenset()}


def test_block_membership_puts_a_cut_city_in_two_blocks() -> None:
    """The shared city of a bowtie belongs to both lobes' blocks."""
    assert len(biconnected_block_membership(_BOWTIE)["c"]) == 2


def test_block_membership_keeps_bowtie_lobes_in_separate_blocks() -> None:
    """The outer cities of a bowtie's two lobes share no block."""
    blocks = biconnected_block_membership(_BOWTIE)
    assert not blocks["a"] & blocks["d"]


def test_survives_any_one_site_loss_true_for_a_cycle() -> None:
    """A cycle has no articulation point, so it survives any single site loss."""
    assert survives_any_one_site_loss({"a", "b", "c"}, {("a", "b"), ("b", "c"), ("a", "c")}) is True


def test_survives_any_one_site_loss_false_for_a_chain() -> None:
    """A chain's middle site is a cut, so the graph does not survive its loss."""
    assert survives_any_one_site_loss({"a", "b", "c"}, {("a", "b"), ("b", "c")}) is False


def test_survives_any_one_site_loss_false_when_disconnected() -> None:
    """A graph in two pieces does not survive the loss of any one site."""
    assert survives_any_one_site_loss({"a", "b", "c", "d"}, {("a", "b"), ("c", "d")}) is False
