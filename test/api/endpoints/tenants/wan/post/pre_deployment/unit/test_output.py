"""Unit tests for the synthesis payload the REST API serves."""

from __future__ import annotations

from typing import Any

import fixtures
from synthesizer.input_graph import PhysicalEdge, Vertex, edge_key
from synthesizer.model import (
    AccessEdge,
    Synthesis,
    SynthesisArtifacts,
    SynthesisMetrics,
    SourceFiles,
)
from synthesizer.output import (
    synthesis_payload,
    included_demand_count,
    sorted_physical_edges,
)

ARTIFACTS = fixtures.ring_artifacts()
SOURCES = fixtures.sample_sources()


def _synthesis_with_homed_demand(source: str) -> Synthesis:
    """A synthesis that homes a single demand vertex to a backbone PoP."""
    return Synthesis(
        backbone_ids=(),
        transit_ids=(),
        access_edges=[AccessEdge(source, "b", 1.0)],
        physical_edge_keys=set(),
        path_uses=[],
        metrics=SynthesisMetrics(0.0, 0.0, 0.0),
    )


def _payload_for(source_vertex: Vertex) -> dict[str, Any]:
    """A payload homing one demand vertex (tenant or provider) onto backbone PoP ``b``."""
    synthesis = _synthesis_with_homed_demand(source_vertex.id)
    vertices = [source_vertex, fixtures.carrier_pop("b")]
    edges = {edge_key("b", "x"): PhysicalEdge("b", "x", 1.0)}
    artifacts = SynthesisArtifacts(vertices, edges, synthesis, ARTIFACTS.validation)
    return synthesis_payload(SourceFiles((), SOURCES.edge_path), artifacts)


def test_synthesis_payload_includes_vertices() -> None:
    """synthesis_payload returns the vertices slice the API serves."""
    assert "vertices" in synthesis_payload(SOURCES, ARTIFACTS)


def test_synthesis_payload_vertices_carry_location() -> None:
    """Each serialized vertex exposes municipality and state for the tooltip."""
    vertices = synthesis_payload(SOURCES, ARTIFACTS)["vertices"]
    assert all(
        "municipality" in vertex["info"] and "state" in vertex["info"] for vertex in vertices
    )


def test_synthesis_payload_summary_reports_backbone_count() -> None:
    """The payload summary reports how many backbone nodes the synthesis selected."""
    summary = synthesis_payload(SOURCES, ARTIFACTS)["summary"]
    assert summary["backbone_count"] == len(ARTIFACTS.synthesis.backbone_ids)


def test_synthesis_payload_summary_lists_backbone_node_names() -> None:
    """The summary lists each selected backbone node by display name."""
    summary = synthesis_payload(SOURCES, ARTIFACTS)["summary"]
    assert len(summary["backbone_nodes"]) == len(ARTIFACTS.synthesis.backbone_ids)


def test_synthesis_payload_summary_publishes_the_floor_under_the_fiber_it_ordered() -> None:
    """The fewest miles the same requirements could have been met with is served too.

    A reader can add up the fiber a synthesis ordered and cannot work out what the least it
    could have run was, since that answer needs the whole carrier map and the tenant's
    requirements together. So the synthesis publishes it, and it is never above the miles the
    synthesis actually holds -- a floor above the thing it floors would be a defect in the
    fiber choice rather than a number to read (GitHub issue #60).
    """
    summary = synthesis_payload(SOURCES, ARTIFACTS)["summary"]
    assert summary["backbone_lower_bound_miles"] <= summary["physical_carrier_miles"]


def test_sorted_physical_edges_is_sorted() -> None:
    """Sorted physical edges is sorted."""
    edges = sorted_physical_edges(ARTIFACTS.synthesis)
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
    assert included_demand_count(vertices, _synthesis_with_homed_demand("homed")) == 1


def test_included_demand_count_excludes_unhomed_demand_vertices() -> None:
    """A loaded demand vertex never homed into the synthesis is not counted."""
    vertices = [fixtures.access_vertex("homed"), fixtures.access_vertex("stranded")]
    assert included_demand_count(vertices, _synthesis_with_homed_demand("homed")) == 1


def test_included_demand_count_excludes_carrier_pops() -> None:
    """Carrier PoPs in the synthesis are not demand vertices and are not counted."""
    vertices = [fixtures.access_vertex("homed"), fixtures.carrier_pop("b")]
    assert included_demand_count(vertices, _synthesis_with_homed_demand("homed")) == 1
