"""Unit tests for the validation helpers."""

from __future__ import annotations

from wan_graph.model import Vertex, edge_key
from wan_synthesizer.model import AccessEdge, Design, DesignMetrics
from wan_synthesizer.validation import (
    access_attachment_counts,
    design_edge_set,
    included_vertex_ids,
    neighbor_degrees,
    vertex_role,
)


def pop(vertex_id: str) -> Vertex:
    """Test helper: build a carrier PoP vertex."""
    return Vertex(
        id=vertex_id, name=vertex_id, tenant="Lumen", kind="PoP", coords=(0.0, 0.0)
    )


def make_design(
    physical_pairs: list[tuple[str, str]],
    *,
    core_ids: tuple[str, ...] = (),
    aggregation_ids: tuple[str, ...] = (),
    transit_ids: tuple[str, ...] = (),
    access_edges: list[AccessEdge] | None = None,
) -> Design:
    """Test helper: build a Design from physical pairs and tier assignments."""
    return Design(
        core_ids=core_ids,
        aggregation_ids=aggregation_ids,
        transit_ids=transit_ids,
        access_edges=access_edges or [],
        physical_edge_keys={edge_key(a, b) for a, b in physical_pairs},
        path_uses=[],
        metrics=DesignMetrics(0.0, 0.0, 0.0),
    )


def test_vertex_role_access_for_non_pop() -> None:
    """Vertex role access for non pop."""
    access = Vertex(
        id="s", name="s", tenant="F-35", kind="Military installation", coords=(0.0, 0.0)
    )
    assert vertex_role("s", make_design([]), access) == "access"


def test_vertex_role_core() -> None:
    """Vertex role core."""
    design = make_design([], core_ids=("a",))
    assert vertex_role("a", design, pop("a")) == "core"


def test_vertex_role_aggregation() -> None:
    """Vertex role aggregation."""
    design = make_design([], aggregation_ids=("a",))
    assert vertex_role("a", design, pop("a")) == "aggregation"


def test_vertex_role_transit() -> None:
    """Vertex role transit."""
    design = make_design([], transit_ids=("a",))
    assert vertex_role("a", design, pop("a")) == "transit"


def test_vertex_role_unused() -> None:
    """Vertex role unused."""
    assert vertex_role("a", make_design([]), pop("a")) == "unused"


def test_included_vertex_ids_covers_access_endpoints() -> None:
    """Included vertex ids covers access endpoints."""
    design = make_design([("a", "b")], access_edges=[AccessEdge("s", "a", 1.0)])
    assert included_vertex_ids(design) == {"a", "b", "s"}


def test_design_edge_set_merges_access_and_physical() -> None:
    """Design edge set merges access and physical."""
    design = make_design([("a", "b")], access_edges=[AccessEdge("s", "a", 1.0)])
    assert design_edge_set(design) == {edge_key("a", "b"), edge_key("s", "a")}


def test_neighbor_degrees_counts_distinct_neighbors() -> None:
    """Neighbor degrees counts distinct neighbors."""
    degrees = neighbor_degrees({"a", "b", "c"}, {("a", "b"), ("b", "c")})
    assert degrees == {"a": 1, "b": 2, "c": 1}


def test_access_attachment_counts_per_source() -> None:
    """Access attachment counts per source."""
    design = make_design(
        [], access_edges=[AccessEdge("s", "a", 1.0), AccessEdge("s", "b", 1.0)]
    )
    assert access_attachment_counts(design) == {"s": 2}


def test_neighbor_degrees_ignores_external_endpoints() -> None:
    """Neighbor degrees ignores external endpoints."""
    degrees = neighbor_degrees({"a", "b"}, {("a", "b"), ("a", "z")})
    assert degrees == {"a": 1, "b": 1}
