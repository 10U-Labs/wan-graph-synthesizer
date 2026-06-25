"""Unit tests for the validation helpers."""

from __future__ import annotations

from synthesizer.input_graph import edge_key
from synthesizer.model import AccessEdge, Design, DesignMetrics
from synthesizer.validation import (
    demand_backbone_homes,
    design_edge_set,
    included_vertex_ids,
    neighbor_degrees,
)


def make_design(
    physical_pairs: list[tuple[str, str]],
    *,
    backbone_ids: tuple[str, ...] = (),
    transit_ids: tuple[str, ...] = (),
    access_edges: list[AccessEdge] | None = None,
) -> Design:
    """Test helper: build a Design from physical pairs and tier assignments."""
    return Design(
        backbone_ids=backbone_ids,
        transit_ids=transit_ids,
        access_edges=access_edges or [],
        physical_edge_keys={edge_key(a, b) for a, b in physical_pairs},
        path_uses=[],
        metrics=DesignMetrics(0.0, 0.0, 0.0),
    )


def test_included_vertex_ids_covers_access_endpoints() -> None:
    """Included vertex ids covers access endpoints."""
    design = make_design([("a", "b")], access_edges=[AccessEdge("s", "a", 1.0)])
    assert included_vertex_ids(design) == {"a", "b", "s"}


def test_included_vertex_ids_covers_the_tier_ids() -> None:
    """Backbone and transit ids are part of the included vertex set."""
    design = make_design([], backbone_ids=("b",), transit_ids=("t",))
    assert included_vertex_ids(design) == {"b", "t"}


def test_design_edge_set_merges_access_and_physical() -> None:
    """Design edge set merges access and physical."""
    design = make_design([("a", "b")], access_edges=[AccessEdge("s", "a", 1.0)])
    assert design_edge_set(design) == {edge_key("a", "b"), edge_key("s", "a")}


def test_neighbor_degrees_counts_distinct_neighbors() -> None:
    """Neighbor degrees counts distinct neighbors."""
    degrees = neighbor_degrees({"a", "b", "c"}, {("a", "b"), ("b", "c")})
    assert degrees == {"a": 1, "b": 2, "c": 1}


def test_neighbor_degrees_ignores_external_endpoints() -> None:
    """Neighbor degrees ignores external endpoints."""
    degrees = neighbor_degrees({"a", "b"}, {("a", "b"), ("a", "z")})
    assert degrees == {"a": 1, "b": 1}


def test_demand_backbone_homes_groups_targets_per_source() -> None:
    """Each demand vertex maps to the distinct backbone nodes it homes to."""
    design = make_design(
        [], access_edges=[AccessEdge("s", "a", 1.0), AccessEdge("s", "b", 1.0)]
    )
    assert demand_backbone_homes(design) == {"s": {"a", "b"}}
