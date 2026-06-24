"""Unit tests for the three-tier design pipeline runner."""

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


def test_run_design_seats_a_forced_location_as_aggregation() -> None:
    """A forced location's fabricated on-net twin is seated on the aggregation tier."""
    design = run_design(
        fixtures.ring_vertices(),
        fixtures.ring_physical_edges(),
        DesignParams(min_core_count=2, forced_aggregation_names=("A1",)),
    ).design
    assert any(agg.startswith("fac_") for agg in design.aggregation_ids)


def test_run_design_seats_a_forced_off_net_site_as_core() -> None:
    """A forced off-net site is seated as a core via its synthesized local-fiber twin."""
    design = run_design(
        fixtures.ring_vertices(),
        fixtures.ring_physical_edges(),
        DesignParams(min_core_count=2, forced_core_names=("Dulles Hub",)),
        off_net_sites=[fixtures.off_net_site("Dulles Hub", 40.5, -100.0)],
    ).design
    assert any(core.startswith("offnet_") for core in design.core_ids)
