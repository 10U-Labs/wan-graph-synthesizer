"""Unit tests for the exact joint core/aggregation optimizer."""

from __future__ import annotations

import pytest

import fixtures
from wan_designer.model import (
    DesignInputs,
    DesignParams,
    Node,
    PhysicalEdge,
)
from wan_designer.optimize import (
    aggregation_core_paths,
    all_pairs_shortest,
    best_aggregation_pair,
    best_design_at_size,
    build_design_for_cores,
    core_mesh_paths,
    cores_mesh,
    dual_homes_to_pair,
    feasible_aggregation_ids,
    nearest_pop_id,
    node_straightness,
    optimize_three_tier_design,
    rank_aggregations,
    second_nearest_miles,
    unit_adjacency,
    _SearchPlan,
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


def _plan(
    candidates: list[str],
    forced: set[str] | None = None,
    exempt: set[str] | None = None,
    strength: dict[str, float] | None = None,
    ranked: dict[str, list[tuple[float, str]]] | None = None,
) -> _SearchPlan:
    """Build a search plan for direct build_design_for_cores tests."""
    return _SearchPlan(
        candidates,
        frozenset(forced or set()),
        frozenset(exempt or set()),
        strength or {},
        ranked or {},
    )


TRIANGLE = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})
TRIANGLE_NODES = [pop("a"), pop("b"), pop("c"), fixtures.access_node("s", 40.0, -99.0)]


def test_core_count_below_two_is_rejected() -> None:
    """Core count below two is rejected."""
    with pytest.raises(ValueError):
        optimize_three_tier_design(TRIANGLE_NODES, TRIANGLE, {}, DesignParams(core_count=1))


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


def test_optimizes_ring_to_a_feasible_design() -> None:
    """Optimizes ring to a feasible design."""
    design = optimize_three_tier_design(
        fixtures.ring_nodes(), fixtures.ring_physical_edges(), {}, fixtures.ring_params()
    )
    assert len(design.core_ids) == 2


def test_core_count_is_honored_as_a_minimum() -> None:
    """Core count is a minimum: a larger floor yields at least that many cores."""
    design = optimize_three_tier_design(
        fixtures.ring_nodes(), fixtures.ring_physical_edges(), {}, DesignParams(core_count=3)
    )
    assert len(design.core_ids) >= 3


def test_no_feasible_design_is_rejected() -> None:
    """No feasible design is rejected when access cannot dual-home."""
    with pytest.raises(ValueError):
        optimize_three_tier_design(TRIANGLE_NODES, TRIANGLE, {}, DesignParams(core_count=2))


def test_single_candidate_per_access_is_infeasible() -> None:
    """Single candidate per access is infeasible."""
    params = DesignParams(core_count=2, aggregation_candidates_per_access=1)
    with pytest.raises(ValueError):
        optimize_three_tier_design(
            fixtures.ring_nodes(), fixtures.ring_physical_edges(), {}, params
        )


def test_forces_a_sentinel_base_as_an_aggregation() -> None:
    """A Sentinel base's nearest PoP is forced into the aggregation tier."""
    base = fixtures.access_node("Minot AFB", 41.0, -99.9)
    nodes = fixtures.ring_nodes() + [base]
    design = optimize_three_tier_design(
        nodes, fixtures.ring_physical_edges(), {}, DesignParams(core_count=2)
    )
    forced = nearest_pop_id(base, [n for n in nodes if n.kind == "carrier_pop"])
    assert forced in design.aggregation_ids


def test_not_enough_core_candidates_is_rejected() -> None:
    """Forcing aggregations can leave too few candidates to be cores."""
    edges = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})
    nodes = [
        pop("a", 0.0, 0.0),
        pop("b", 0.0, 1.0),
        pop("c", 0.0, 2.0),
        fixtures.access_node("Minot AFB", 0.0, 0.0),
        fixtures.access_node("Malmstrom AFB", 0.0, 1.0),
    ]
    with pytest.raises(ValueError):
        optimize_three_tier_design(nodes, edges, {}, DesignParams(core_count=2))


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


def test_nearest_pop_id_picks_the_closest() -> None:
    """Nearest pop id picks the closest."""
    pops = [pop("far", 0.0, 50.0), pop("near", 0.0, 1.0)]
    assert nearest_pop_id(fixtures.access_node("s", 0.0, 0.0), pops) == "near"


def test_second_nearest_miles_returns_the_second_distance() -> None:
    """Second nearest miles returns the second distance."""
    pops = [pop("a", 0.0, 0.0), pop("b", 0.0, 1.0), pop("c", 0.0, 50.0)]
    assert second_nearest_miles(fixtures.access_node("s", 0.0, 0.0), pops) > 0.0


def test_best_aggregation_pair_is_none_with_single_candidate() -> None:
    """Best aggregation pair is none with single candidate."""
    access = fixtures.access_node("s")
    plan = _plan([], ranked={access.id: [(0.0, "g1")]})
    assert best_aggregation_pair(access, {"g1"}, DesignParams(), plan) is None


def _near_far_plan(exempt: set[str] | None = None) -> tuple[Node, _SearchPlan]:
    """Access site pre-ranked with one near and one far aggregation, for cap tests."""
    access = fixtures.access_node("s", 0.0, 0.0)
    ranked = {access.id: [(0.0, "near"), (3450.0, "far")]}
    return access, _plan([], exempt=exempt, ranked=ranked)


def test_best_aggregation_pair_drops_aggregations_beyond_the_cap() -> None:
    """Best aggregation pair drops aggregations beyond the cap."""
    access, plan = _near_far_plan()
    params = DesignParams(max_last_mile_miles=100.0)
    assert best_aggregation_pair(access, {"near", "far"}, params, plan) is None


def test_best_aggregation_pair_exempts_remote_sites_from_the_cap() -> None:
    """Best aggregation pair exempts remote sites from the cap."""
    access, plan = _near_far_plan(exempt={"s"})
    assert best_aggregation_pair(access, {"near", "far"}, DesignParams(), plan) is not None


def test_rank_aggregations_breaks_distance_ties_by_strength() -> None:
    """Equally near aggregations are ranked stronger-first."""
    access = fixtures.access_node("s", 0.0, 0.0)
    by_id = {"weak": pop("weak", 0.0, 1.0), "strong": pop("strong", 0.0, -1.0)}
    ranked = rank_aggregations(access, {"weak", "strong"}, by_id, {"strong": 5.0, "weak": 0.0})
    assert ranked[0][1] == "strong"


def test_feasible_aggregation_ids_skips_infeasible_aggregations() -> None:
    """Feasible aggregation ids skip aggregations that cannot dual-home."""
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
    assert feasible_aggregation_ids(("c1", "c2"), inputs, _plan([])) == {"gA"}


def test_dual_homes_to_pair_memoizes_feasibility() -> None:
    """Dual homes to pair records its computed feasibility in the cache."""
    edges = physical({("g", "c1"): 1.0, ("g", "c2"): 1.0, ("c1", "c2"): 1.0})
    inputs = _inputs_from_edges(["g", "c1", "c2"], edges, {"g", "c1", "c2"})
    cache: dict[tuple[str, str, str], bool] = {}
    dual_homes_to_pair("g", ("c1", "c2"), inputs, cache)
    assert cache[("g", "c1", "c2")] is True


def test_dual_homes_to_pair_uses_cached_result() -> None:
    """Dual homes to pair trusts a cached verdict over the live graph."""
    inputs = _inputs_from_edges(["g", "c1", "c2"], physical({("g", "c1"): 1.0}), {"g"})
    cache = {("g", "c1", "c2"): True}
    assert dual_homes_to_pair("g", ("c1", "c2"), inputs, cache) is True


def test_cores_mesh_false_when_cores_disconnected() -> None:
    """Cores mesh is false when two cores cannot reach each other."""
    edges = physical({("a", "b"): 1.0, ("c", "d"): 1.0})
    adjacency = unit_adjacency(edges)
    distances, _predecessors = all_pairs_shortest(
        [pop("a"), pop("b"), pop("c"), pop("d")], adjacency
    )
    assert not cores_mesh(("a", "c"), distances)


def _mesh_inputs() -> DesignInputs:
    """A four-PoP full mesh with one access site, for core-selection tests."""
    edges = physical(
        {
            ("a", "b"): 1.0, ("a", "c"): 1.0, ("a", "d"): 1.0,
            ("b", "c"): 1.0, ("b", "d"): 1.0, ("c", "d"): 1.0,
        }
    )
    return _inputs_from_edges(
        ["a", "b", "c", "d"], edges, {"a", "b", "c", "d"},
        [fixtures.access_node("s", 0.0, 0.0)],
    )


@pytest.mark.parametrize(
    "strength, ranked",
    [
        # Strength is primary: {a,b} wins though it forces the costlier last-mile.
        (
            {"a": 10.0, "b": 10.0, "c": 1.0, "d": 1.0},
            {"s": [(0.5, "a"), (0.6, "b"), (5.0, "c"), (5.1, "d")]},
        ),
        # Equal strength: the least-last-mile set {a,b} breaks the tie.
        (
            {"a": 10.0, "b": 10.0, "c": 10.0, "d": 10.0},
            {"s": [(0.1, "c"), (0.2, "d"), (5.0, "a"), (5.1, "b")]},
        ),
    ],
)
def test_best_design_at_size_selects_strongest_then_least_last_mile(
    strength: dict[str, float],
    ranked: dict[str, list[tuple[float, str]]],
) -> None:
    """Cores are chosen by strength first, with last-mile only breaking ties."""
    plan = _plan(["a", "b", "c", "d"], strength=strength, ranked=ranked)
    params = DesignParams(core_count=2, max_last_mile_miles=100000.0)
    design = best_design_at_size(_mesh_inputs(), params, plan, 2)
    assert design is not None and set(design.core_ids) == {"a", "b"}


def test_build_design_returns_none_without_aggregations() -> None:
    """Build design returns none without aggregations."""
    edges = physical({("c1", "c2"): 1.0})
    inputs = _inputs_from_edges(
        ["c1", "c2"], edges, {"c1", "c2"}, [fixtures.access_node("s")]
    )
    assert build_design_for_cores(("c1", "c2"), inputs, DesignParams(), _plan([])) is None


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
        ["c1", "c2", "c3", "g1", "g2", "z"], edges, {"g1", "g2"}, [fixtures.access_node("s")]
    )
    assert build_design_for_cores(("c1", "c2", "c3"), inputs, DesignParams(), _plan([])) is None


def test_build_design_returns_none_when_a_forced_aggregation_cannot_route() -> None:
    """Build design returns none when a forced aggregation cannot dual-home."""
    edges = physical({("c1", "g1"): 1.0, ("c2", "g1"): 1.0, ("c1", "c2"): 1.0, ("z", "g1"): 1.0})
    inputs = _inputs_from_edges(
        ["c1", "c2", "g1", "z"], edges, {"g1", "z"}, [fixtures.access_node("s")]
    )
    plan = _plan([], forced={"z"})
    assert build_design_for_cores(("c1", "c2"), inputs, DesignParams(), plan) is None
