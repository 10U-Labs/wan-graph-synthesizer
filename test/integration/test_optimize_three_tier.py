"""Integration test: the optimizer over the synthetic ring graph.

A six-PoP ring is 2-connected, so every aggregation reaches two cores over
node-disjoint paths; a degree-one spur confirms such PoPs are never aggregations.
"""

from __future__ import annotations

import fixtures

ARTIFACTS = fixtures.ring_artifacts()
FORCED = fixtures.forced_aggregation_artifacts("P3")
FORCED_CORE = fixtures.forced_core_artifacts("P4")


def test_forced_pop_is_placed_in_the_aggregation_tier() -> None:
    """A PoP named on the force-aggregation list is honored as an aggregation."""
    assert "P3" in FORCED.design.aggregation_ids


def test_forced_aggregation_is_not_also_made_a_core() -> None:
    """Forcing a PoP onto the aggregation tier never lands it in the core tier."""
    assert "P3" not in FORCED.design.core_ids


def test_forced_pop_is_placed_in_the_core_tier() -> None:
    """A PoP named on the force-core list is honored as a core."""
    assert "P4" in FORCED_CORE.design.core_ids


def test_honors_the_core_count_minimum() -> None:
    """The design has at least the minimum number of cores."""
    assert len(ARTIFACTS.design.core_ids) >= 2


def test_degree_one_spur_is_not_an_aggregation() -> None:
    """Degree one spur is not an aggregation."""
    assert "P6" not in ARTIFACTS.design.aggregation_ids


def test_degree_one_spur_is_not_a_core() -> None:
    """Degree one spur is not a core."""
    assert "P6" not in ARTIFACTS.design.core_ids


def test_every_aggregation_dual_homed_to_cores() -> None:
    """Every aggregation dual homed to cores."""
    assert ARTIFACTS.validation["aggregations_dual_homed_to_cores"] is True


def test_cores_form_full_mesh() -> None:
    """Cores form full mesh."""
    assert ARTIFACTS.validation["cores_full_mesh"] is True


def test_access_nodes_dual_homed() -> None:
    """Access nodes dual homed."""
    assert ARTIFACTS.validation["access_nodes_with_two_aggregation_links"] is True
