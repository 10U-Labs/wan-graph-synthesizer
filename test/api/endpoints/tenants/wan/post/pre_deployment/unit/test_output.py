from __future__ import annotations

from typing import Any

import fixtures
from synthesizer.input_graph import FiberSegment, Site, link_key
from synthesizer.model import (
    AccessPath,
    Synthesis,
    SynthesisArtifacts,
    SynthesisMetrics,
    SourceFiles,
)
from synthesizer.output import (
    synthesis_payload,
    included_demand_count,
    sorted_fiber_segments,
)

ARTIFACTS = fixtures.ring_artifacts()
SOURCES = fixtures.sample_sources()


def _synthesis_with_homed_demand(source: str) -> Synthesis:
    return Synthesis(
        backbone_ids=(),
        transit_ids=(),
        access_paths=[AccessPath(source, "b", 1.0)],
        fiber_segment_keys=set(),
        path_uses=[],
        metrics=SynthesisMetrics(0.0, 0.0, 0.0),
    )


def _payload_for(source_site: Site) -> dict[str, Any]:
    synthesis = _synthesis_with_homed_demand(source_site.id)
    sites = [source_site, fixtures.carrier_pop("b")]
    links = {link_key("b", "x"): FiberSegment("b", "x", 1.0)}
    artifacts = SynthesisArtifacts(sites, links, synthesis, ARTIFACTS.validation)
    return synthesis_payload(SourceFiles((), SOURCES.link_path), artifacts)


def test_synthesis_payload_includes_sites() -> None:
    assert "sites" in synthesis_payload(SOURCES, ARTIFACTS)


def test_synthesis_payload_sites_carry_location() -> None:
    sites = synthesis_payload(SOURCES, ARTIFACTS)["sites"]
    assert all(
        "municipality" in site["info"] and "state" in site["info"] for site in sites
    )


def test_synthesis_payload_summary_reports_backbone_count() -> None:
    summary = synthesis_payload(SOURCES, ARTIFACTS)["summary"]
    assert summary["backbone_count"] == len(ARTIFACTS.synthesis.backbone_ids)


def test_synthesis_payload_summary_lists_backbone_node_names() -> None:
    summary = synthesis_payload(SOURCES, ARTIFACTS)["summary"]
    assert len(summary["backbone_nodes"]) == len(ARTIFACTS.synthesis.backbone_ids)


def test_synthesis_payload_summary_publishes_the_floor_under_the_fiber_it_ordered() -> None:
    summary = synthesis_payload(SOURCES, ARTIFACTS)["summary"]
    assert summary["backbone_lower_bound_miles"] <= summary["physical_carrier_miles"]


def test_sorted_fiber_segments_is_sorted() -> None:
    links = sorted_fiber_segments(ARTIFACTS.synthesis)
    assert links == sorted(links)


def test_tenant_demand_link_is_labelled_tenant_to_backbone() -> None:
    payload = _payload_for(fixtures.access_site("s"))
    assert payload["access_paths"][0]["link_kind"] == "tenant_to_backbone"


def test_provider_demand_link_is_labelled_provider_to_backbone() -> None:
    payload = _payload_for(fixtures.provider_site("r"))
    assert payload["access_paths"][0]["link_kind"] == "provider_to_backbone"


def test_included_demand_count_counts_a_homed_demand_site() -> None:
    sites = [fixtures.access_site("homed")]
    assert included_demand_count(sites, _synthesis_with_homed_demand("homed")) == 1


def test_included_demand_count_excludes_unhomed_demand_sites() -> None:
    sites = [fixtures.access_site("homed"), fixtures.access_site("stranded")]
    assert included_demand_count(sites, _synthesis_with_homed_demand("homed")) == 1


def test_included_demand_count_excludes_carrier_pops() -> None:
    sites = [fixtures.access_site("homed"), fixtures.carrier_pop("b")]
    assert included_demand_count(sites, _synthesis_with_homed_demand("homed")) == 1
