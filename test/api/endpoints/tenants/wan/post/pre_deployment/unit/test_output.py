"""Unit tests for the synthesis payload the REST API serves."""

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
    """A synthesis that homes a single demand site to a backbone PoP."""
    return Synthesis(
        backbone_ids=(),
        transit_ids=(),
        access_paths=[AccessPath(source, "b", 1.0)],
        fiber_segment_keys=set(),
        path_uses=[],
        metrics=SynthesisMetrics(0.0, 0.0, 0.0),
    )


def _payload_for(source_site: Site) -> dict[str, Any]:
    """A payload homing one demand site (tenant or provider) onto backbone PoP ``b``."""
    synthesis = _synthesis_with_homed_demand(source_site.id)
    sites = [source_site, fixtures.carrier_pop("b")]
    links = {link_key("b", "x"): FiberSegment("b", "x", 1.0)}
    artifacts = SynthesisArtifacts(sites, links, synthesis, ARTIFACTS.validation)
    return synthesis_payload(SourceFiles((), SOURCES.link_path), artifacts)


def test_synthesis_payload_includes_sites() -> None:
    """synthesis_payload returns the sites slice the API serves."""
    assert "sites" in synthesis_payload(SOURCES, ARTIFACTS)


def test_synthesis_payload_sites_carry_location() -> None:
    """Each serialized site exposes municipality and state for the tooltip."""
    sites = synthesis_payload(SOURCES, ARTIFACTS)["sites"]
    assert all(
        "municipality" in site["info"] and "state" in site["info"] for site in sites
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


def test_sorted_fiber_segments_is_sorted() -> None:
    """Sorted physical links is sorted."""
    links = sorted_fiber_segments(ARTIFACTS.synthesis)
    assert links == sorted(links)


def test_tenant_demand_link_is_labelled_tenant_to_backbone() -> None:
    """A tenant-site demand homing reads as a tenant_to_backbone access link."""
    payload = _payload_for(fixtures.access_site("s"))
    assert payload["access_paths"][0]["link_kind"] == "tenant_to_backbone"


def test_provider_demand_link_is_labelled_provider_to_backbone() -> None:
    """A provider-region demand homing reads as a provider_to_backbone access link."""
    payload = _payload_for(fixtures.provider_site("r"))
    assert payload["access_paths"][0]["link_kind"] == "provider_to_backbone"


def test_included_demand_count_counts_a_homed_demand_site() -> None:
    """A demand site homed to a backbone node counts toward the demand tally."""
    sites = [fixtures.access_site("homed")]
    assert included_demand_count(sites, _synthesis_with_homed_demand("homed")) == 1


def test_included_demand_count_excludes_unhomed_demand_sites() -> None:
    """A loaded demand site never homed into the synthesis is not counted."""
    sites = [fixtures.access_site("homed"), fixtures.access_site("stranded")]
    assert included_demand_count(sites, _synthesis_with_homed_demand("homed")) == 1


def test_included_demand_count_excludes_carrier_pops() -> None:
    """Carrier PoPs in the synthesis are not demand sites and are not counted."""
    sites = [fixtures.access_site("homed"), fixtures.carrier_pop("b")]
    assert included_demand_count(sites, _synthesis_with_homed_demand("homed")) == 1
