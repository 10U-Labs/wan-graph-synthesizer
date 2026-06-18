"""Unit tests for the design payload the REST API serves."""

from __future__ import annotations

import fixtures
from wan_designer.output import design_payload, sorted_physical_edges, tier_breakdown

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


def test_tier_breakdown_counts_standalone_cores() -> None:
    """Cores whose twin is not a seated aggregation count as standalone cores."""
    breakdown = tier_breakdown(("core_a", "core_b"), ("agg_x",))
    assert breakdown["standalone_core_count"] == 2


def test_tier_breakdown_has_no_colocated_cores_without_twins() -> None:
    """No core is dual-role when no twin id is seated as an aggregation."""
    breakdown = tier_breakdown(("core_a", "core_b"), ("agg_x",))
    assert breakdown["colocated_core_count"] == 0


def test_tier_breakdown_counts_standalone_aggregations() -> None:
    """Aggregations that are not any core's twin count as standalone aggregations."""
    breakdown = tier_breakdown(("core_a", "core_b"), ("agg_x",))
    assert breakdown["standalone_aggregation_count"] == 1


def test_tier_breakdown_counts_a_dual_role_core() -> None:
    """A core whose twin id is a seated aggregation counts as CORE+AGGR."""
    breakdown = tier_breakdown(("core_a", "core_b"), ("aggr_core_a", "agg_x"))
    assert breakdown["colocated_core_count"] == 1


def test_tier_breakdown_excludes_a_twin_from_standalone_cores() -> None:
    """A dual-role core is removed from the standalone-core tally."""
    breakdown = tier_breakdown(("core_a", "core_b"), ("aggr_core_a", "agg_x"))
    assert breakdown["standalone_core_count"] == 1


def test_tier_breakdown_excludes_a_twin_from_standalone_aggregations() -> None:
    """A seated twin is not counted as a standalone aggregation."""
    breakdown = tier_breakdown(("core_a", "core_b"), ("aggr_core_a", "agg_x"))
    assert breakdown["standalone_aggregation_count"] == 1
