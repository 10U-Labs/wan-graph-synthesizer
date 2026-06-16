"""Integration test: the optimizer over the synthetic ring graph.

A six-PoP ring is 2-connected, so every aggregation reaches two cores over
vertex-disjoint paths; a degree-one spur confirms such PoPs are never aggregations.
"""

from __future__ import annotations

from pathlib import Path

import fixtures

ARTIFACTS = fixtures.ring_artifacts()
FORCED = fixtures.forced_aggregation_artifacts("P3")
FORCED_ROADM = fixtures.forced_roadm_aggregation_artifacts("P3")
FORCED_CORE = fixtures.forced_core_artifacts("P4")


def test_forced_pop_is_placed_in_the_aggregation_tier() -> None:
    """A PoP named on the force-aggregation list is honored as an aggregation."""
    assert "P3" in FORCED.design.aggregation_ids


def test_forced_roadm_is_seated_though_roadm_aggregation_is_disabled() -> None:
    """A pinned ROADM is honored as an aggregation even with allow_roadm_aggregation false.

    This is the mechanism the Joint Great Falls and Minot pins rely on: both are
    ROADMs, and the operator pin must override the ROADM-aggregation gate.
    """
    assert "P3" in FORCED_ROADM.design.aggregation_ids


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


def test_core_backbone_respects_degree_cap() -> None:
    """No core links to more than the default of three other cores on the backbone."""
    assert ARTIFACTS.validation["core_backbone_max_degree"] <= 3


def test_access_vertices_dual_homed() -> None:
    """Access vertices dual homed."""
    assert ARTIFACTS.validation["access_vertices_with_two_aggregation_links"] is True


def _core_states(directory: Path) -> list[str]:
    """States of the cores in a population-anchored design over the scenario."""
    artifacts = fixtures.population_artifacts(directory)
    return [v.info.state for v in artifacts.vertices if v.id in artifacts.design.core_ids]


def test_population_design_seats_one_core_per_state(tmp_path: Path) -> None:
    """Population anchoring never seats two cores in the same state."""
    states = _core_states(tmp_path)
    assert len(states) == len(set(states))


def test_population_access_state_gets_two_aggregations(tmp_path: Path) -> None:
    """An access-bearing state is given at least two aggregation points."""
    artifacts = fixtures.population_artifacts(tmp_path)
    seated = artifacts.design.aggregation_ids
    colorado = [v for v in artifacts.vertices if v.id in seated and v.info.state == "CO"]
    assert len(colorado) >= 2


def test_population_cored_metro_aggregates_on_its_second_city(tmp_path: Path) -> None:
    """Denver cores Colorado, so its aggregation is Aurora (the metro's 2nd city), not a twin."""
    artifacts = fixtures.population_artifacts(tmp_path)
    roles = (artifacts.design.core_ids, artifacts.design.aggregation_ids)
    assert ("denver_co" in roles[0], "aurora_co" in roles[1], "aggr_denver_co" in roles[1]) == (
        True,
        True,
        False,
    )
