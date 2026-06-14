"""Unit tests for the cluster-driven core/aggregation optimizer."""

from __future__ import annotations

import pytest

import fixtures
from wan_designer.model import (
    AccessEdge,
    Design,
    DesignInputs,
    DesignMetrics,
    DesignParams,
    Node,
    PathUse,
    PhysicalEdge,
    RoleOverrides,
    edge_key,
    haversine_miles,
)
from wan_designer.optimize import (
    aggregation_core_paths,
    all_pairs_shortest,
    apply_role_overrides,
    assign_access,
    best_design_at_size,
    build_design_for_cores,
    cluster_diameter,
    cluster_local_heads,
    colocation_edges,
    complete_homes,
    core_combination_count,
    core_combinations,
    core_mesh_paths,
    cores_mesh,
    coverage_score,
    dual_homes_to_pair,
    enumeration_limit,
    feasible_aggregation_ids,
    nearest_pop_id,
    node_straightness,
    optimize_three_tier_design,
    reject_override_conflicts,
    required_core_ids,
    resolve_pinned_ids,
    search_best_design,
    unit_adjacency,
    _SearchPlan,
)

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from
access = fixtures.access_node


def _inputs_from_edges(
    edge_ids: list[str],
    edges: dict[tuple[str, str], PhysicalEdge],
    eligible: set[str],
    access_nodes: list[Node] | None = None,
    coords: dict[str, tuple[float, float]] | None = None,
) -> DesignInputs:
    """Build DesignInputs over a unit-weight graph for direct optimizer tests."""
    places = coords or {}
    pops = [pop(node_id, *places.get(node_id, (0.0, 0.0))) for node_id in edge_ids]
    adjacency = unit_adjacency(edges)
    distances, predecessors = all_pairs_shortest(pops, adjacency)
    return DesignInputs(
        access_nodes=access_nodes if access_nodes is not None else [],
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
    strength: dict[str, float] | None = None,
    clusters: list[list[str]] | None = None,
    sentinel: set[str] | None = None,
) -> _SearchPlan:
    """Build a search plan for direct optimizer tests."""
    return _SearchPlan(
        candidates,
        frozenset(forced or set()),
        strength or {},
        clusters=clusters or [],
        sentinel_ids=frozenset(sentinel or set()),
    )


def _required_plan(candidates: list[str], required: set[str]) -> _SearchPlan:
    """Build a search plan with required cores, for core-combination tests."""
    return _SearchPlan(
        candidates, frozenset(), {}, required_cores=frozenset(required)
    )


TRIANGLE = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})
TRIANGLE_NODES = [pop("a"), pop("b"), pop("c"), access("s", 40.0, -99.0)]


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
    """Optimizes ring to a feasible design with at least the minimum cores."""
    design = optimize_three_tier_design(
        fixtures.ring_nodes(), fixtures.ring_physical_edges(), {}, fixtures.ring_params()
    )
    assert len(design.core_ids) >= 2


def test_core_count_is_honored_as_a_minimum() -> None:
    """Core count is a minimum: a larger floor yields at least that many cores."""
    design = optimize_three_tier_design(
        fixtures.ring_nodes(), fixtures.ring_physical_edges(), {}, DesignParams(core_count=3)
    )
    assert len(design.core_ids) >= 3


def test_no_feasible_design_is_rejected() -> None:
    """No feasible design is rejected when access cannot reach two aggregations."""
    with pytest.raises(ValueError):
        optimize_three_tier_design(TRIANGLE_NODES, TRIANGLE, {}, DesignParams(core_count=2))


def test_forces_a_sentinel_base_as_an_aggregation() -> None:
    """A Sentinel base's nearest PoP is forced into the aggregation tier."""
    base = access("Minot AFB", 41.0, -99.9)
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
        access("Minot AFB", 0.0, 0.0),
        access("Malmstrom AFB", 0.0, 1.0),
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
    assert nearest_pop_id(access("s", 0.0, 0.0), pops) == "near"


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


MESH_EDGES = physical(
    {
        ("a", "b"): 1.0, ("a", "c"): 1.0, ("a", "d"): 1.0,
        ("b", "c"): 1.0, ("b", "d"): 1.0, ("c", "d"): 1.0,
    }
)
# c and d sit beside the access site; a and b are far. Whichever pair is cores,
# the design that homes the site to the near pair (c, d) wins on last-mile.
MESH_COORDS = {"a": (0.0, 50.0), "b": (0.0, 51.0), "c": (0.0, 1.0), "d": (0.0, 2.0)}


def _mesh_inputs() -> DesignInputs:
    """A four-PoP full mesh with one access site, for core-selection tests."""
    return _inputs_from_edges(
        ["a", "b", "c", "d"], MESH_EDGES, {"a", "b", "c", "d"},
        [access("s", 0.0, 0.0)], MESH_COORDS,
    )


@pytest.mark.parametrize(
    "strength",
    [
        {"a": 10.0, "b": 10.0, "c": 1.0, "d": 1.0},  # strength primary: {a,b} strongest
        {"a": 10.0, "b": 10.0, "c": 10.0, "d": 10.0},  # equal: {a,b} wins least-last-mile
    ],
)
def test_best_design_at_size_selects_strongest_then_least_last_mile(
    strength: dict[str, float],
) -> None:
    """Cores are chosen by strength first, with last-mile only breaking ties."""
    design = best_design_at_size(_mesh_inputs(), _plan(["a", "b", "c", "d"], strength=strength), 2)
    assert design is not None and set(design.core_ids) == {"a", "b"}


# g1 and g2 each reach both cores over node-disjoint paths; the cores mesh.
DUAL_EDGES = physical(
    {
        ("g1", "c1"): 1.0, ("g1", "c2"): 1.0,
        ("g2", "c1"): 1.0, ("g2", "c2"): 1.0, ("c1", "c2"): 1.0,
    }
)
DUAL_IDS = ["g1", "g2", "c1", "c2"]
CLUSTER_ACCESS = {"A1": (0.0, 0.0), "A2": (0.0, 0.03), "A3": (0.0, 0.06)}


def _assign(
    g1_coord: tuple[float, float], g2_coord: tuple[float, float]
) -> tuple[list[AccessEdge], set[str]] | None:
    """Run cluster-driven assignment over the dual-aggregation graph."""
    coords = {"g1": g1_coord, "g2": g2_coord}
    access_nodes = [access(name, lat, lon) for name, (lat, lon) in CLUSTER_ACCESS.items()]
    inputs = _inputs_from_edges(DUAL_IDS, DUAL_EDGES, {"g1", "g2"}, access_nodes, coords)
    plan = _plan([], clusters=[list(CLUSTER_ACCESS)])
    return assign_access(("c1", "c2"), inputs, plan)


def test_assign_access_places_two_cluster_heads() -> None:
    """A cluster with two local PoPs adopts both as its aggregation heads."""
    result = _assign((0.0, 0.0), (0.0, 0.05))
    assert result is not None and {"g1", "g2"} <= result[1]


def test_assign_access_completes_a_single_head_cluster_by_reuse() -> None:
    """A cluster with one local PoP gains its second home from the other facility."""
    result = _assign((0.0, 0.0), (3.0, 3.0))
    assert result is not None and {"g1", "g2"} <= result[1]


def test_assign_access_completes_a_cluster_with_no_local_head() -> None:
    """A cluster whose PoPs are all distant still homes every member to two."""
    result = _assign((3.0, 0.0), (3.0, 1.0))
    assert result is not None and len(result[0]) == 2 * len(CLUSTER_ACCESS)


def test_cluster_diameter_is_the_farthest_member_pair() -> None:
    """A cluster's diameter is the greatest distance between two members."""
    members = [access("a", 0.0, 0.0), access("b", 0.0, 1.0), access("c", 0.0, 3.0)]
    assert cluster_diameter(members) == pytest.approx(haversine_miles(members[0], members[2]))


def test_cluster_local_heads_excludes_a_distant_pop() -> None:
    """A PoP beyond the cluster's extent is not chosen as a head."""
    members = [access("a", 0.0, 0.0), access("b", 0.0, 0.1), access("c", 0.0, 0.2)]
    by_id = {"near": pop("near", 0.0, 0.05), "far": pop("far", 0.0, 9.0)}
    assert "far" not in cluster_local_heads(members, set(by_id), by_id)


def test_cluster_local_heads_caps_at_two() -> None:
    """A cluster takes at most two heads even when more PoPs are local."""
    members = [access("a", 0.0, 0.0), access("b", 0.0, 0.1), access("c", 0.0, 0.2)]
    by_id = {key: pop(key, 0.0, off) for key, off in (("x", 0.0), ("y", 0.1), ("z", 0.2))}
    assert len(cluster_local_heads(members, set(by_id), by_id)) == 2


HOMES_POPS = {key: pop(key, 0.0, off) for key, off in (("x", 1.0), ("y", 2.0), ("z", 3.0))}


@pytest.mark.parametrize(
    "current, selected, feasible, expected",
    [
        ([], {"x", "y"}, {"x", "y", "z"}, {"x", "y"}),  # reuse fills both homes
        ([], set(), {"x", "y"}, {"x", "y"}),  # nothing to reuse: build two
        ([], set(), {"x"}, {"x"}),  # only one reachable: returns one
        (["x"], {"y"}, {"x", "y", "z"}, {"x", "y"}),  # keep the prefilled home, add one
    ],
)
def test_complete_homes(
    current: list[str], selected: set[str], feasible: set[str], expected: set[str]
) -> None:
    """Homes prefer reuse, then build, and keep any prefilled home."""
    result = complete_homes(access("s", 0.0, 0.0), current, selected, feasible, HOMES_POPS)
    assert set(result) == expected


def test_required_core_is_fixed_into_every_core_set() -> None:
    """Required cores appear in every candidate set the search considers."""
    plan = _required_plan(["a", "b", "c"], {"a"})
    assert core_combinations(plan, 2) == [("a", "b"), ("a", "c")]


def test_core_combinations_empty_when_size_below_required() -> None:
    """No core set exists when more cores are required than the size allows."""
    plan = _required_plan(["a", "b"], {"a", "b"})
    assert core_combinations(plan, 1) == []


def test_core_combination_count_zero_when_size_below_required() -> None:
    """The count is zero when more cores are required than the size allows."""
    plan = _required_plan(["a", "b"], {"a", "b"})
    assert core_combination_count(plan, 1) == 0


def test_required_core_ids_picks_the_eligible_named_pop() -> None:
    """Salt Lake City is required as a core when it is an eligible PoP."""
    pops = [pop("Salt Lake City, UT"), pop("other")]
    assert required_core_ids(pops, {"Salt Lake City, UT", "other"}) == frozenset(
        {"Salt Lake City, UT"}
    )


def test_required_core_ids_skips_an_ineligible_named_pop() -> None:
    """A required city that is not an eligible PoP is not forced as a core."""
    assert required_core_ids([pop("Salt Lake City, UT")], {"other"}) == frozenset()


def test_coverage_score_weights_a_base_by_its_sites() -> None:
    """A base's 165 sites pull far harder on the score than a single access link."""
    paths = [
        PathUse("aggregation_to_core", "base", "c1", ("base", "x", "c1"), 0.0),
        PathUse("aggregation_to_core", "agg", "c1", ("agg", "c1"), 0.0),
    ]
    design = Design(("c1",), (), (), [], set(), paths, DesignMetrics(0.0, 0.0, 0.0))
    plan = _plan([], sentinel={"base"})
    assert coverage_score(design, plan) == 165 * 2 + 1 * 1


def test_enumeration_limit_grows_with_available_memory() -> None:
    """The core sets the search may enumerate scale with the machine's free RAM."""
    assert enumeration_limit(32 * 10**9) > enumeration_limit(16 * 10**9)


def test_search_stops_when_the_core_space_is_too_large() -> None:
    """The sweep stops rather than enumerate more core sets than RAM can hold."""
    inputs = _inputs_from_edges([], {}, set(), [])
    plan = _plan([f"c{index}" for index in range(40)])
    with pytest.raises(ValueError):
        search_best_design(inputs, DesignParams(core_count=20), plan)


def test_build_design_returns_none_without_aggregations() -> None:
    """Build design returns none without two feasible aggregations."""
    edges = physical({("c1", "c2"): 1.0})
    inputs = _inputs_from_edges(["c1", "c2"], edges, {"c1", "c2"}, [access("s")])
    assert build_design_for_cores(("c1", "c2"), inputs, _plan([])) is None


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
        ["c1", "c2", "c3", "g1", "g2", "z"], edges, {"g1", "g2"}, [access("s")]
    )
    assert build_design_for_cores(("c1", "c2", "c3"), inputs, _plan([])) is None


def test_build_design_returns_none_when_a_forced_aggregation_cannot_route() -> None:
    """Build design returns none when a forced aggregation cannot dual-home."""
    edges = physical({("c1", "g1"): 1.0, ("c2", "g1"): 1.0, ("c1", "c2"): 1.0, ("z", "g1"): 1.0})
    inputs = _inputs_from_edges(
        ["c1", "c2", "g1", "z"], edges, {"g1", "z"}, [access("s")]
    )
    plan = _plan([], forced={"z"})
    assert build_design_for_cores(("c1", "c2"), inputs, plan) is None


def test_resolve_pinned_ids_maps_a_known_name_to_its_id() -> None:
    """A known PoP name resolves to its node id."""
    assert resolve_pinned_ids(("Denver, CO",), {"Denver, CO": "d"}, "force-core") == {"d"}


def test_resolve_pinned_ids_rejects_an_unknown_name() -> None:
    """An unknown PoP name is rejected rather than silently ignored."""
    with pytest.raises(ValueError):
        resolve_pinned_ids(("Nowhere",), {"Denver, CO": "d"}, "force-core")


def test_reject_override_conflicts_rejects_excluding_a_forced_pop() -> None:
    """A PoP that is both excluded and forced is rejected."""
    with pytest.raises(ValueError):
        reject_override_conflicts({"a"}, set(), {"a"})


def test_colocation_edges_duplicate_a_cores_handoffs_onto_its_twin() -> None:
    """The twin gains an in-facility cross-connect plus each of the core's handoffs."""
    edges = physical({("m", "z"): 1.0, ("a", "m"): 1.0, ("p", "q"): 1.0})
    result = colocation_edges("m", "aggr_m", edges)
    assert set(result) == {
        edge_key("m", "aggr_m"), edge_key("aggr_m", "z"), edge_key("a", "aggr_m")
    }


def test_apply_role_overrides_splits_a_co_located_pop() -> None:
    """Pinning a PoP as both core and aggregation forces its split-off twin."""
    params = DesignParams(forced_core_names=("Hub",), forced_aggregation_names=("Hub",))
    _nodes, _edges, overrides = apply_role_overrides(
        [pop("Hub"), pop("z")], physical({("Hub", "z"): 1.0}), params
    )
    assert "aggr_Hub" in overrides.forced_aggregation_ids


def test_optimize_honors_a_forced_core_override() -> None:
    """A forced-core override is fixed into the selected core tier."""
    design = optimize_three_tier_design(
        fixtures.ring_nodes(), fixtures.ring_physical_edges(), {},
        DesignParams(core_count=2), RoleOverrides(forced_core_ids=frozenset({"P3"})),
    )
    assert "P3" in design.core_ids
