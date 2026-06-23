"""Unit tests for the design payload the REST API serves."""

from __future__ import annotations

import fixtures
from wan_synthesizer.model import AccessEdge, Design, DesignMetrics
from wan_synthesizer.output import (
    design_payload,
    included_access_count,
    sorted_physical_edges,
    tier_breakdown,
)

ARTIFACTS = fixtures.ring_artifacts()
SOURCES = fixtures.sample_sources()


def _design_with_homed_access() -> Design:
    """A design that homes a single access vertex to an aggregation PoP."""
    return Design(
        core_ids=(),
        aggregation_ids=("agg",),
        transit_ids=(),
        access_edges=[AccessEdge("homed", "agg", 1.0)],
        physical_edge_keys=set(),
        path_uses=[],
        metrics=DesignMetrics(0.0, 0.0, 0.0),
    )


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


def test_included_access_count_counts_a_homed_access_vertex() -> None:
    """An access vertex homed to an aggregation counts toward the ACCESS tally."""
    vertices = [fixtures.access_vertex("homed")]
    assert included_access_count(vertices, _design_with_homed_access()) == 1


def test_included_access_count_excludes_unhomed_access_vertices() -> None:
    """A loaded access vertex never homed into the design is not counted."""
    vertices = [fixtures.access_vertex("homed"), fixtures.access_vertex("stranded")]
    assert included_access_count(vertices, _design_with_homed_access()) == 1


def test_included_access_count_excludes_carrier_pops() -> None:
    """Carrier PoPs in the design are not access vertices and are not counted."""
    vertices = [fixtures.access_vertex("homed"), fixtures.carrier_pop("agg")]
    assert included_access_count(vertices, _design_with_homed_access()) == 1
