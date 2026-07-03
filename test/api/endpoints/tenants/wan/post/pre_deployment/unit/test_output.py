"""Unit tests for the design payload the REST API serves."""

from __future__ import annotations

from typing import Any

import fixtures
from synthesizer.input_graph import PhysicalEdge, Vertex, edge_key
from synthesizer.model import (
    AccessEdge,
    Design,
    DesignArtifacts,
    DesignMetrics,
    SourceFiles,
)
from synthesizer.output import (
    design_payload,
    included_demand_count,
    sorted_physical_edges,
)

ARTIFACTS = fixtures.ring_artifacts()
SOURCES = fixtures.sample_sources()


def _design_with_homed_demand(source: str) -> Design:
    """A design that homes a single demand vertex to a backbone PoP."""
    return Design(
        backbone_ids=(),
        transit_ids=(),
        access_edges=[AccessEdge(source, "b", 1.0)],
        physical_edge_keys=set(),
        path_uses=[],
        metrics=DesignMetrics(0.0, 0.0, 0.0),
    )


def _payload_for(source_vertex: Vertex) -> dict[str, Any]:
    """A payload homing one demand vertex (tenant or provider) onto backbone PoP ``b``."""
    design = _design_with_homed_demand(source_vertex.id)
    vertices = [source_vertex, fixtures.carrier_pop("b")]
    edges = {edge_key("b", "x"): PhysicalEdge("b", "x", 1.0)}
    artifacts = DesignArtifacts(vertices, edges, design, ARTIFACTS.validation)
    return design_payload(SourceFiles((), SOURCES.edge_path), artifacts)


def test_design_payload_includes_vertices() -> None:
    """design_payload returns the vertices slice the API serves."""
    assert "vertices" in design_payload(SOURCES, ARTIFACTS)


def test_design_payload_vertices_carry_location() -> None:
    """Each serialized vertex exposes municipality and state for the tooltip."""
    vertices = design_payload(SOURCES, ARTIFACTS)["vertices"]
    assert all(
        "municipality" in vertex["info"] and "state" in vertex["info"] for vertex in vertices
    )


def test_design_payload_summary_reports_backbone_count() -> None:
    """The payload summary reports how many backbone nodes the design selected."""
    summary = design_payload(SOURCES, ARTIFACTS)["summary"]
    assert summary["backbone_count"] == len(ARTIFACTS.design.backbone_ids)


def test_design_payload_summary_lists_backbone_node_names() -> None:
    """The summary lists each selected backbone node by display name."""
    summary = design_payload(SOURCES, ARTIFACTS)["summary"]
    assert len(summary["backbone_nodes"]) == len(ARTIFACTS.design.backbone_ids)


def test_sorted_physical_edges_is_sorted() -> None:
    """Sorted physical edges is sorted."""
    edges = sorted_physical_edges(ARTIFACTS.design)
    assert edges == sorted(edges)


def test_tenant_demand_edge_is_labelled_tenant_to_backbone() -> None:
    """A tenant-site demand homing reads as a tenant_to_backbone access edge."""
    payload = _payload_for(fixtures.access_vertex("s"))
    assert payload["access_edges"][0]["edge_kind"] == "tenant_to_backbone"


def test_provider_demand_edge_is_labelled_provider_to_backbone() -> None:
    """A provider-region demand homing reads as a provider_to_backbone access edge."""
    payload = _payload_for(fixtures.provider_vertex("r"))
    assert payload["access_edges"][0]["edge_kind"] == "provider_to_backbone"


def test_included_demand_count_counts_a_homed_demand_vertex() -> None:
    """A demand vertex homed to a backbone node counts toward the demand tally."""
    vertices = [fixtures.access_vertex("homed")]
    assert included_demand_count(vertices, _design_with_homed_demand("homed")) == 1


def test_included_demand_count_excludes_unhomed_demand_vertices() -> None:
    """A loaded demand vertex never homed into the design is not counted."""
    vertices = [fixtures.access_vertex("homed"), fixtures.access_vertex("stranded")]
    assert included_demand_count(vertices, _design_with_homed_demand("homed")) == 1


def test_included_demand_count_excludes_carrier_pops() -> None:
    """Carrier PoPs in the design are not demand vertices and are not counted."""
    vertices = [fixtures.access_vertex("homed"), fixtures.carrier_pop("b")]
    assert included_demand_count(vertices, _design_with_homed_demand("homed")) == 1
