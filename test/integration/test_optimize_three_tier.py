"""Integration test: the optimizer over the synthetic ring graph.

A six-PoP ring is 2-connected, so every aggregation reaches two cores over
vertex-disjoint paths; a degree-one spur confirms such PoPs are never aggregations.
"""

from __future__ import annotations

from pathlib import Path

import fixtures
from wan_designer.model import DesignArtifacts, DesignParams
from wan_designer.service import run_design

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


def test_a_core_may_also_serve_as_an_aggregation() -> None:
    """The search may seat a core's co-located twin so the core also aggregates."""
    twinned = {
        agg[len("aggr_"):]
        for agg in ARTIFACTS.design.aggregation_ids
        if agg.startswith("aggr_")
    }
    assert twinned & set(ARTIFACTS.design.core_ids)


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


def test_cores_connect_to_at_least_three_others() -> None:
    """Every core links to at least three others once there are more than three cores."""
    assert ARTIFACTS.validation["cores_connect_to_three_others"] is True


def test_access_vertices_dual_homed() -> None:
    """Access vertices dual homed."""
    assert ARTIFACTS.validation["access_vertices_with_two_aggregation_links"] is True


def _justified_artifacts(directory: Path) -> DesignArtifacts:
    """Optimize over the ring of justified installations with A1 forced as an aggregation."""
    paths = fixtures.write_justified_solvable_inputs(directory)
    params = DesignParams(min_core_count=2, forced_aggregation_names=("A1",))
    return run_design(paths, params, False)


def test_forced_installation_is_seated_as_an_aggregation(tmp_path: Path) -> None:
    """A forced installation's facility twin lands on the aggregation tier."""
    design = _justified_artifacts(tmp_path).design
    assert any(aggregation.startswith("fac_") for aggregation in design.aggregation_ids)


def test_installation_facility_is_never_a_core(tmp_path: Path) -> None:
    """A forced installation's twin is aggregation-only -- it never reaches the core tier."""
    design = _justified_artifacts(tmp_path).design
    assert not any(core.startswith("fac_") for core in design.core_ids)


def test_justified_design_dual_homes_every_aggregation(tmp_path: Path) -> None:
    """Every aggregation -- installation facilities included -- dual-homes to two cores."""
    artifacts = _justified_artifacts(tmp_path)
    assert artifacts.validation["aggregations_dual_homed_to_cores"] is True


def test_justified_design_dual_homes_every_access_vertex(tmp_path: Path) -> None:
    """Every access vertex still reaches two aggregation facilities."""
    artifacts = _justified_artifacts(tmp_path)
    assert artifacts.validation["access_vertices_with_two_aggregation_links"] is True
