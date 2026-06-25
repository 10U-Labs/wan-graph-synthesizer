"""Unit tests for the pure graph and parsing helpers."""

from __future__ import annotations

import math

import pytest

from synthesizer.graphs import (
    articulation_points,
    bridges,
    connected_components,
    dijkstra,
    path_edge_keys,
    reconstruct_path,
)
from synthesizer.input_graph import Vertex, edge_key, haversine_miles


def make_vertex(vertex_id: str, lat: float, lon: float) -> Vertex:
    """Test helper: build make vertex."""
    return Vertex(id=vertex_id, name=vertex_id, kind="PoP", coords=(lat, lon))


def test_edge_key_orders_pair() -> None:
    """Edge key orders pair."""
    assert edge_key("b", "a") == ("a", "b")


def test_edge_key_rejects_self_loop() -> None:
    """Edge key rejects self loop."""
    with pytest.raises(ValueError):
        edge_key("a", "a")


def test_haversine_zero_distance() -> None:
    """Haversine zero distance."""
    vertex = make_vertex("x", 40.0, -100.0)
    assert haversine_miles(vertex, vertex) == pytest.approx(0.0)


def test_haversine_known_distance() -> None:
    # New York to Los Angeles is roughly 2450 miles.
    """Haversine known distance."""
    new_york = make_vertex("ny", 40.7128, -74.006)
    los_angeles = make_vertex("la", 34.0522, -118.2437)
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
    edges = {("a", "b"), ("c", "d")}
    assert len(connected_components(ids, edges)) == 2


def test_articulation_point_detected() -> None:
    """Articulation point detected."""
    ids = {"a", "b", "c"}
    edges = {("a", "b"), ("b", "c")}
    assert articulation_points(ids, edges) == {"b"}


def test_cycle_has_no_articulation_points() -> None:
    """Cycle has no articulation points."""
    ids = {"a", "b", "c"}
    edges = {("a", "b"), ("b", "c"), ("a", "c")}
    assert articulation_points(ids, edges) == set()


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


def test_path_edge_keys_for_a_three_vertex_path() -> None:
    """Path edge keys for a three vertex path."""
    assert path_edge_keys(("a", "b", "c")) == {edge_key("a", "b"), edge_key("b", "c")}


def test_dfs_root_with_two_children_is_an_articulation_point() -> None:
    """Dfs root with two children is an articulation point."""
    assert articulation_points({"a", "b", "c"}, {("a", "b"), ("a", "c")}) == {"a"}


def test_connected_components_ignores_external_endpoints() -> None:
    """Connected components ignores external endpoints."""
    components = connected_components({"a", "b"}, {("a", "b"), ("a", "z")})
    assert components == [["a", "b"]]


def test_bridges_names_every_cut_edge_in_a_chain() -> None:
    """Every edge of a chain is a bridge, since removing it splits the chain."""
    assert bridges({"a", "b", "c"}, {("a", "b"), ("b", "c")}) == {
        edge_key("a", "b"),
        edge_key("b", "c"),
    }


def test_cycle_has_no_bridges() -> None:
    """A cycle has no bridges: every edge lies on a cycle, so none is a cut edge."""
    assert bridges({"a", "b", "c"}, {("a", "b"), ("b", "c"), ("a", "c")}) == set()
