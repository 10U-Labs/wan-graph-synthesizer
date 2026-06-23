"""Integration test: the synthesizer over the synthetic ring graph.

A six-PoP ring is 2-connected, so every aggregation reaches two cores over
vertex-disjoint paths; a degree-one spur confirms such PoPs are never aggregations.
"""

from __future__ import annotations

from pathlib import Path

import fixtures
from wan_graph.model import edge_key
from fixtures import run_design
from wan_synthesizer.model import DesignArtifacts, DesignParams, ForcedConnection
from wan_synthesizer.validation import core_backbone_pairs

ARTIFACTS = fixtures.ring_artifacts()
FORCED = fixtures.forced_aggregation_artifacts("P3")
FORCED_ROADM = fixtures.forced_roadm_aggregation_artifacts("P3")
FORCED_CORE = fixtures.forced_core_artifacts("P4")
PROHIBITED = fixtures.prohibited_aggregation_artifacts("P4")

# Three forced-connection designs over the ring, each resolved through the
# operator-pin path so the asserted edges reflect genuinely honored requests.
FORCED_CORE_LINK = fixtures.forced_connection_artifacts(
    DesignParams(min_core_count=2, forced_core_names=("P0", "P3")),
    (ForcedConnection("core-core", "P0", "P3"),),
)
FORCED_AGG_LINK = fixtures.forced_connection_artifacts(
    DesignParams(min_core_count=2, forced_core_names=("P0",), forced_aggregation_names=("P3",)),
    (ForcedConnection("aggregation-core", "P3", "P0"),),
)
FORCED_ACCESS_LINK = fixtures.forced_connection_artifacts(
    DesignParams(min_core_count=2, forced_aggregation_names=("P3",)),
    (ForcedConnection("access-aggregation", "A1", "P3"),),
)


def test_forced_core_connection_appears_in_the_backbone() -> None:
    """A forced core-core connection is present in the routed core backbone."""
    assert edge_key("P0", "P3") in core_backbone_pairs(FORCED_CORE_LINK.design)


def test_forced_aggregation_connection_routes_to_the_named_core() -> None:
    """A forced aggregation-core connection routes the aggregation to that core."""
    assert any(
        use.purpose == "aggregation_to_core" and use.source == "P3" and use.target == "P0"
        for use in FORCED_AGG_LINK.design.path_uses
    )


def test_forced_access_connection_homes_the_access_node_to_the_named_aggregation() -> None:
    """A forced access-aggregation connection homes the access node to that aggregation."""
    assert any(
        edge.source == "A1" and edge.target == "P3"
        for edge in FORCED_ACCESS_LINK.design.access_edges
    )


def test_forced_connection_designs_stay_valid() -> None:
    """Forcing connections does not break the aggregation dual-homing invariant."""
    assert FORCED_AGG_LINK.validation["aggregations_dual_homed_to_cores"] is True


def test_forced_pop_is_placed_in_the_aggregation_tier() -> None:
    """A PoP named on the force-aggregation list is honored as an aggregation."""
    assert "P3" in FORCED.design.aggregation_ids


def test_forced_roadm_is_seated_as_an_aggregation() -> None:
    """A pinned ROADM is honored as an aggregation.

    ROADMs are eligible like any other point now, and a force always wins regardless;
    this is the mechanism the Joint Great Falls and Minot ROADM pins rely on.
    """
    assert "P3" in FORCED_ROADM.design.aggregation_ids


def test_forced_pop_is_placed_in_the_core_tier() -> None:
    """A PoP named on the force-core list is honored as a core."""
    assert "P4" in FORCED_CORE.design.core_ids


def test_prohibited_pop_is_kept_off_the_aggregation_tier() -> None:
    """A prohibited PoP -- and its co-located twin -- never reach the aggregation tier."""
    assert not ({"P4", "aggr_P4"} & set(PROHIBITED.design.aggregation_ids))


def test_prohibited_pop_may_still_serve_as_a_core() -> None:
    """Barring a PoP from the aggregation tier does not bar it from the core tier."""
    assert "P4" in PROHIBITED.design.core_ids


def test_prohibited_design_stays_valid() -> None:
    """Prohibiting an aggregation does not break the dual-homing invariant."""
    assert PROHIBITED.validation["aggregations_dual_homed_to_cores"] is True


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


def test_cores_meet_the_backbone_link_target() -> None:
    """Every core wires to its configured number of nearest cores on the backbone."""
    assert ARTIFACTS.validation["cores_meet_backbone_link_target"] is True


def test_access_vertices_dual_homed() -> None:
    """Access vertices dual homed."""
    assert ARTIFACTS.validation["access_vertices_with_required_aggregation_links"] is True


def _forced_installation_artifacts(directory: Path) -> DesignArtifacts:
    """Synthesize over the ring of installations with A1 forced as an aggregation."""
    paths = fixtures.write_solvable_design_paths(directory)
    params = DesignParams(min_core_count=2, forced_aggregation_names=("A1",))
    return run_design(paths, params)


def test_forced_installation_is_seated_as_an_aggregation(tmp_path: Path) -> None:
    """A forced installation's facility twin lands on the aggregation tier."""
    design = _forced_installation_artifacts(tmp_path).design
    assert any(aggregation.startswith("fac_") for aggregation in design.aggregation_ids)


def test_forced_design_dual_homes_every_aggregation(tmp_path: Path) -> None:
    """Every aggregation -- installation facilities included -- dual-homes to two cores."""
    artifacts = _forced_installation_artifacts(tmp_path)
    assert artifacts.validation["aggregations_dual_homed_to_cores"] is True


def test_forced_design_dual_homes_every_access_vertex(tmp_path: Path) -> None:
    """Every access vertex still reaches two aggregation facilities."""
    artifacts = _forced_installation_artifacts(tmp_path)
    assert artifacts.validation["access_vertices_with_required_aggregation_links"] is True


def test_forced_off_net_site_is_seated_as_an_aggregation(tmp_path: Path) -> None:
    """A forced off-net site's local-fiber twin lands on the aggregation tier."""
    paths, name = fixtures.write_off_net_solvable_inputs(tmp_path)
    design = run_design(
        paths, DesignParams(min_core_count=2, forced_aggregation_names=(name,))
    ).design
    assert any(aggregation.startswith("offnet_") for aggregation in design.aggregation_ids)


def test_off_net_design_dual_homes_every_aggregation(tmp_path: Path) -> None:
    """An off-net aggregation twin dual-homes to two cores like any other aggregation."""
    paths, name = fixtures.write_off_net_solvable_inputs(tmp_path)
    artifacts = run_design(
        paths, DesignParams(min_core_count=2, forced_aggregation_names=(name,))
    )
    assert artifacts.validation["aggregations_dual_homed_to_cores"] is True
