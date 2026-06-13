"""Integration test: the optimizer over the synthetic ring graph.

A six-PoP ring is 2-connected, so every aggregation reaches two cores over
node-disjoint paths; a degree-one spur confirms such PoPs are never aggregations.
"""

from __future__ import annotations

import fixtures

ARTIFACTS = fixtures.ring_artifacts()


def test_selects_two_cores() -> None:
    """Selects two cores."""
    assert len(ARTIFACTS.design.core_ids) == 2


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
