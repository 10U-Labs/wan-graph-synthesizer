"""Unit tests for the optimizer's error paths and routing helpers."""

from __future__ import annotations

import pytest

import fixtures
from wan_designer.model import (
    Design,
    DesignInputs,
    DesignMetrics,
    DesignParams,
    PathUse,
    edge_key,
)
from wan_designer.parsing import build_adjacency
from wan_designer.optimize import (
    aggregation_core_map,
    aggregation_core_paths,
    all_pairs_shortest,
    best_aggregation_pair,
    build_design_for_cores,
    core_mesh_paths,
    optimize_three_tier_design,
    scored_design,
)

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from

TRIANGLE = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})
TRIANGLE_NODES = [pop("a"), pop("b"), pop("c"), fixtures.access_node("s", 40.0, -99.0)]


def test_core_count_below_two_is_rejected() -> None:
    """Core count below two is rejected."""
    with pytest.raises(ValueError):
        optimize_three_tier_design(TRIANGLE_NODES, TRIANGLE, {}, DesignParams(core_count=1))


def test_core_count_above_three_is_rejected() -> None:
    """Core count above three is rejected."""
    with pytest.raises(ValueError):
        optimize_three_tier_design(TRIANGLE_NODES, TRIANGLE, {}, DesignParams(core_count=4))


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
    params = DesignParams(core_count=2, core_candidate_limit=1, min_core_separation_miles=0.0)
    with pytest.raises(ValueError):
        optimize_three_tier_design(TRIANGLE_NODES, TRIANGLE, {}, params)


def test_no_feasible_design_is_rejected() -> None:
    """No feasible design is rejected."""
    params = DesignParams(core_count=2, min_core_separation_miles=1e9, core_candidate_limit=10)
    with pytest.raises(ValueError):
        optimize_three_tier_design(TRIANGLE_NODES, TRIANGLE, {}, params)


def test_single_candidate_per_access_is_infeasible() -> None:
    """Single candidate per access is infeasible."""
    params = DesignParams(
        core_count=2,
        aggregation_candidates_per_access=1,
        min_core_separation_miles=0.0,
        core_candidate_limit=10,
    )
    with pytest.raises(ValueError):
        optimize_three_tier_design(
            fixtures.ring_nodes(), fixtures.ring_physical_edges(), {}, params
        )


def test_aggregation_core_paths_infeasible_through_bottleneck() -> None:
    """Aggregation core paths infeasible through bottleneck."""
    edges = physical({("S", "X"): 1.0, ("X", "C1"): 1.0, ("X", "C2"): 1.0})
    _distance, paths = aggregation_core_paths("S", ("C1", "C2"), build_adjacency(edges), edges)
    assert not paths


def test_core_mesh_paths_empty_when_cores_disconnected() -> None:
    """Core mesh paths empty when cores disconnected."""
    edges = physical({("a", "b"): 1.0, ("c", "d"): 1.0})
    adjacency = build_adjacency(edges)
    distances, predecessors = all_pairs_shortest(
        [pop("a"), pop("b"), pop("c"), pop("d")], adjacency
    )
    assert not core_mesh_paths(("a", "c"), distances, predecessors)


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


def test_scored_design_penalizes_a_broken_design() -> None:
    """Scored design penalizes a broken design."""
    design = Design(
        core_ids=(),
        aggregation_ids=(),
        transit_ids=("a", "b", "c", "d"),
        access_edges=[],
        physical_edge_keys={edge_key("a", "b"), edge_key("c", "d")},
        path_uses=[],
        metrics=DesignMetrics(0.0, 0.0, 0.0),
    )
    nodes = [pop("a"), pop("b"), pop("c"), pop("d")]
    assert scored_design(nodes, design).metrics.score >= 1_000_000.0


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
    adjacency = build_adjacency(edges)
    ids = ["gA", "x1", "x2", "gB", "y", "c1", "c2"]
    distances, predecessors = all_pairs_shortest([pop(i) for i in ids], adjacency)
    inputs = DesignInputs(
        access_nodes=[],
        carrier_pops=[pop(i) for i in ids],
        physical_edges=edges,
        eligible_aggregation_ids={"gA", "gB", "c1", "c2"},
        adjacency=adjacency,
        all_distances=distances,
        all_predecessors=predecessors,
    )
    feasible = aggregation_core_map(("c1", "c2"), inputs)
    assert set(feasible) == {"gA"}


def test_build_design_returns_none_without_aggregations() -> None:
    """Build design returns none without aggregations."""
    edges = physical({("c1", "c2"): 1.0})
    adjacency = build_adjacency(edges)
    distances, predecessors = all_pairs_shortest([pop("c1"), pop("c2")], adjacency)
    inputs = DesignInputs(
        access_nodes=[fixtures.access_node("s")],
        carrier_pops=[pop("c1"), pop("c2")],
        physical_edges=edges,
        eligible_aggregation_ids={"c1", "c2"},
        adjacency=adjacency,
        all_distances=distances,
        all_predecessors=predecessors,
    )
    assert build_design_for_cores(("c1", "c2"), inputs, DesignParams()) is None
