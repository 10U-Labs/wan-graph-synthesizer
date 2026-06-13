"""Unit tests for the optimizer's error paths and routing helpers."""

from __future__ import annotations

import pytest

import fixtures
from wan_designer.model import (
    DesignInputs,
    DesignParams,
    Node,
    PathUse,
    PhysicalEdge,
)
from wan_designer.optimize import (
    aggregation_core_map,
    aggregation_core_paths,
    all_pairs_shortest,
    best_aggregation_pair,
    build_design_for_cores,
    core_mesh_paths,
    node_straightness,
    optimize_three_tier_design,
    unit_adjacency,
)

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from


def _inputs_from_edges(
    edge_ids: list[str],
    edges: dict[tuple[str, str], PhysicalEdge],
    eligible: set[str],
    access: list[Node] | None = None,
) -> DesignInputs:
    """Build DesignInputs over a unit-weight graph for direct optimizer tests."""
    pops = [pop(i) for i in edge_ids]
    adjacency = unit_adjacency(edges)
    distances, predecessors = all_pairs_shortest(pops, adjacency)
    return DesignInputs(
        access_nodes=access if access is not None else [],
        carrier_pops=pops,
        physical_edges=edges,
        eligible_aggregation_ids=eligible,
        adjacency=adjacency,
        all_distances=distances,
        all_predecessors=predecessors,
    )

TRIANGLE = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})
TRIANGLE_NODES = [pop("a"), pop("b"), pop("c"), fixtures.access_node("s", 40.0, -99.0)]


def test_core_count_below_two_is_rejected() -> None:
    """Core count below two is rejected."""
    with pytest.raises(ValueError):
        optimize_three_tier_design(TRIANGLE_NODES, TRIANGLE, {}, DesignParams(core_count=1))


def test_core_count_is_honored_as_a_minimum() -> None:
    """Core count is a minimum: a larger floor yields at least that many cores."""
    design = optimize_three_tier_design(
        fixtures.ring_nodes(),
        fixtures.ring_physical_edges(),
        {},
        DesignParams(core_count=3, core_candidate_limit=10),
    )
    assert len(design.core_ids) >= 3


def test_unknown_pop_ids_are_rejected() -> None:
    """Unknown pop ids are rejected."""
    with pytest.raises(ValueError):
        optimize_three_tier_design(
            [pop("a"), pop("b")], physical({("a", "c"): 1.0}), {}, DesignParams()
        )


def test_pop_without_edges_is_rejected() -> None:
    """Pop without edges is rejected."""
    with pytest.raises(ValueError):
        optimize_three_tier_design(
            [pop("a"), pop("b"), pop("c")], physical({("a", "b"): 1.0}), {}, DesignParams()
        )


def test_not_enough_eligible_pops_is_rejected() -> None:
    """Not enough eligible pops is rejected."""
    with pytest.raises(ValueError):
        optimize_three_tier_design(
            [pop("a"), pop("b")], physical({("a", "b"): 1.0}), {}, DesignParams()
        )


def test_not_enough_core_candidates_is_rejected() -> None:
    """Not enough core candidates is rejected."""
    params = DesignParams(core_count=2, core_candidate_limit=1)
    with pytest.raises(ValueError):
        optimize_three_tier_design(TRIANGLE_NODES, TRIANGLE, {}, params)


def test_no_feasible_design_is_rejected() -> None:
    """No feasible design is rejected when access cannot dual-home."""
    params = DesignParams(core_count=2, core_candidate_limit=10)
    with pytest.raises(ValueError):
        optimize_three_tier_design(TRIANGLE_NODES, TRIANGLE, {}, params)


def test_single_candidate_per_access_is_infeasible() -> None:
    """Single candidate per access is infeasible."""
    params = DesignParams(
        core_count=2,
        aggregation_candidates_per_access=1,
        core_candidate_limit=10,
    )
    with pytest.raises(ValueError):
        optimize_three_tier_design(
            fixtures.ring_nodes(), fixtures.ring_physical_edges(), {}, params
        )


def test_aggregation_core_paths_infeasible_through_bottleneck() -> None:
    """Aggregation core paths infeasible through bottleneck."""
    edges = physical({("S", "X"): 1.0, ("X", "C1"): 1.0, ("X", "C2"): 1.0})
    _distance, paths = aggregation_core_paths("S", ("C1", "C2"), unit_adjacency(edges), edges)
    assert not paths


def test_core_mesh_paths_empty_when_cores_disconnected() -> None:
    """Core mesh paths empty when cores disconnected."""
    edges = physical({("a", "b"): 1.0, ("c", "d"): 1.0})
    adjacency = unit_adjacency(edges)
    distances, predecessors = all_pairs_shortest(
        [pop("a"), pop("b"), pop("c"), pop("d")], adjacency
    )
    assert not core_mesh_paths(("a", "c"), distances, predecessors, edges)


def test_node_straightness_is_zero_without_reachable_nodes() -> None:
    """Node straightness is zero when no other PoP is reachable."""
    assert node_straightness("a", {"a": pop("a")}, {}) == 0.0


def test_node_straightness_skips_zero_length_hops() -> None:
    """Node straightness ignores hops between coincident PoPs."""
    by_id = {"a": pop("a", 0.0, 0.0), "b": pop("b", 0.0, 0.0)}
    assert node_straightness("a", by_id, {"b": "a"}) == 0.0


def test_best_aggregation_pair_is_none_with_single_candidate() -> None:
    """Best aggregation pair is none with single candidate."""
    aggregation_core: dict[str, tuple[float, list[PathUse]]] = {
        "g1": (0.0, []),
        "g2": (0.0, []),
    }
    by_id = {"g1": pop("g1"), "g2": pop("g2")}
    pair = best_aggregation_pair(
        fixtures.access_node("s"),
        aggregation_core,
        by_id,
        DesignParams(aggregation_candidates_per_access=1),
    )
    assert pair is None


def test_aggregation_core_map_skips_infeasible_aggregations() -> None:
    """Aggregation core map skips infeasible aggregations."""
    edges = physical(
        {
            ("gA", "x1"): 1.0,
            ("x1", "c1"): 1.0,
            ("gA", "x2"): 1.0,
            ("x2", "c2"): 1.0,
            ("gB", "y"): 1.0,
            ("y", "c1"): 1.0,
            ("y", "c2"): 1.0,
        }
    )
    ids = ["gA", "x1", "x2", "gB", "y", "c1", "c2"]
    inputs = _inputs_from_edges(ids, edges, {"gA", "gB", "c1", "c2"})
    feasible = aggregation_core_map(("c1", "c2"), inputs)
    assert set(feasible) == {"gA"}


def test_build_design_returns_none_without_aggregations() -> None:
    """Build design returns none without aggregations."""
    edges = physical({("c1", "c2"): 1.0})
    inputs = _inputs_from_edges(
        ["c1", "c2"], edges, {"c1", "c2"}, [fixtures.access_node("s")]
    )
    assert build_design_for_cores(("c1", "c2"), inputs, DesignParams()) is None


def test_build_design_returns_none_when_cores_are_not_meshed() -> None:
    """Build design returns none when a core cannot reach the others."""
    edges = physical(
        {
            ("c1", "g1"): 1.0,
            ("c2", "g1"): 1.0,
            ("c1", "g2"): 1.0,
            ("c2", "g2"): 1.0,
            ("c3", "z"): 1.0,
        }
    )
    inputs = _inputs_from_edges(
        ["c1", "c2", "c3", "g1", "g2", "z"],
        edges,
        {"g1", "g2"},
        [fixtures.access_node("s")],
    )
    assert build_design_for_cores(("c1", "c2", "c3"), inputs, DesignParams()) is None
