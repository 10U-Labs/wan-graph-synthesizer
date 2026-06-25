"""Unit tests for the two-tier design pipeline runner."""

from __future__ import annotations

import fixtures
from synthesizer.model import DesignParams
from fixtures import run_design


def test_run_design_is_connected() -> None:
    """Run design over a solvable graph validates as connected."""
    artifacts = run_design(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(), fixtures.ring_params()
    )
    assert artifacts.validation["connected"] is True


def test_run_design_honors_a_forced_backbone_pop() -> None:
    """A forced carrier PoP is seated on the backbone the pipeline produces."""
    design = run_design(
        fixtures.ring_vertices(),
        fixtures.ring_physical_edges(),
        DesignParams(
            min_backbone_count=2,
            forced_backbone_names=("P3",),
            datacenter_cities=fixtures.ring_datacenter_cities(),
        ),
    ).design
    assert "P3" in design.backbone_ids


def test_run_design_seats_a_forced_off_net_site_as_backbone() -> None:
    """A forced off-net site is seated as a backbone node via its local-fiber twin."""
    site = fixtures.off_net_site("Dulles Hub", 40.5, -100.0)
    design = run_design(
        fixtures.ring_vertices(),
        fixtures.ring_physical_edges(),
        DesignParams(
            min_backbone_count=2,
            forced_backbone_names=("Dulles Hub",),
            datacenter_cities=fixtures.ring_datacenter_cities()
            | {(site.info.municipality, site.info.state)},
        ),
        off_net_sites=[site],
    ).design
    assert any(node.startswith("offnet_") for node in design.backbone_ids)
