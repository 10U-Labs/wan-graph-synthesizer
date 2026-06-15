"""Unit tests for the design payload the REST API serves."""

from __future__ import annotations

import fixtures
from wan_designer.output import design_payload, sorted_physical_edges

ARTIFACTS = fixtures.ring_artifacts()
SOURCES = fixtures.sample_sources()


def test_design_payload_includes_vertices() -> None:
    """design_payload returns the vertices slice the API serves."""
    assert "vertices" in design_payload(SOURCES, ARTIFACTS)


def test_design_payload_vertices_carry_location() -> None:
    """Each serialized vertex exposes municipality and state for the tooltip."""
    vertices = design_payload(SOURCES, ARTIFACTS)["vertices"]
    assert all(
        "municipality" in vertex["info"] and "state" in vertex["info"] for vertex in vertices
    )


def test_sorted_physical_edges_is_sorted() -> None:
    """Sorted physical edges is sorted."""
    edges = sorted_physical_edges(ARTIFACTS.design)
    assert edges == sorted(edges)
