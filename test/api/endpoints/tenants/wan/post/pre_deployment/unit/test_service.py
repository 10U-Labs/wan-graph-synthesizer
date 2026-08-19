"""Unit tests for the two-tier synthesis pipeline runner."""

from __future__ import annotations

import fixtures
from synthesizer.model import SynthesisParams
from fixtures import run_synthesis


def test_run_synthesis_is_connected() -> None:
    """Run synthesis over a solvable graph validates as connected."""
    artifacts = run_synthesis(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(), fixtures.ring_params()
    )
    assert artifacts.validation["connected"] is True


def test_run_synthesis_honors_a_forced_backbone_pop() -> None:
    """A forced carrier PoP is seated on the backbone the pipeline produces."""
    synthesis = run_synthesis(
        fixtures.ring_vertices(),
        fixtures.ring_physical_edges(),
        SynthesisParams(
            min_backbone_count=2,
            forced_backbone_names=("P3",),
            datacenter_cities=fixtures.ring_datacenter_cities(),
        ),
    ).synthesis
    assert "P3" in synthesis.backbone_ids


def test_run_synthesis_seats_a_forced_off_net_site_as_backbone() -> None:
    """A forced off-net site is seated as a backbone node via its local-fiber twin."""
    site = fixtures.off_net_site("Dulles Hub", 40.5, -100.0)
    synthesis = run_synthesis(
        fixtures.ring_vertices(),
        fixtures.ring_physical_edges(),
        SynthesisParams(
            min_backbone_count=2,
            forced_backbone_names=("Dulles Hub",),
            datacenter_cities=fixtures.ring_datacenter_cities()
            | {(site.info.municipality, site.info.state)},
        ),
        off_net_sites=[site],
    ).synthesis
    assert any(node.startswith("offnet_") for node in synthesis.backbone_ids)
