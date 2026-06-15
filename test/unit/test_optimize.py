"""Unit tests for the cluster-driven core/aggregation optimizer."""

from __future__ import annotations

import math

import pytest

import fixtures
from wan_designer.graphs import connected_components
from wan_designer.model import (
    AccessEdge,
    DesignInputs,
    DesignParams,
    Vertex,
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
    select_core_backbone_pairs,
    dual_homes_to_pair,
    enumeration_limit,
    feasible_aggregation_ids,
    nearest_pop_id,
    vertex_straightness,
    optimize_three_tier_design,
    reject_override_conflicts,
    resolve_pinned_ids,
    search_best_design,
    unit_adjacency,
    _SearchPlan,
)

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from
access = fixtures.access_vertex


def _inputs_from_edges(
    edge_ids: list[str],
    edges: dict[tuple[str, str], PhysicalEdge],
    eligible: set[str],
    access_vertices: list[Vertex] | None = None,
    coords: dict[str, tuple[float, float]] | None = None,
) -> DesignInputs:
    """Build DesignInputs over a unit-weight graph for direct optimizer tests."""
    places = coords or {}
    pops = [pop(vertex_id, *places.get(vertex_id, (0.0, 0.0))) for vertex_id in edge_ids]
    adjacency = unit_adjacency(edges)
    distances, predecessors = all_pairs_shortest(pops, adjacency)
    return DesignInputs(
        access_vertices=access_vertices if access_vertices is not None else [],
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
) -> _SearchPlan:
    """Build a search plan for direct optimizer tests."""
    return _SearchPlan(
        candidates,
        frozenset(forced or set()),
        strength or {},
        clusters=clusters or [],
    )


def _required_plan(candidates: list[str], required: set[str]) -> _SearchPlan:
    """Build a search plan with required cores, for core-combination tests."""
    return _SearchPlan(
        candidates, frozenset(), {}, required_cores=frozenset(required)
    )


TRIANGLE = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})
TRIANGLE_VERTICES = [pop("a"), pop("b"), pop("c"), access("s", 40.0, -99.0)]


def test_min_core_count_below_two_is_rejected() -> None:
    """A minimum core count below two is rejected."""
    with pytest.raises(ValueError):
        optimize_three_tier_design(TRIANGLE_VERTICES, TRIANGLE, {}, DesignParams(min_core_count=1))


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
        fixtures.ring_vertices(), fixtures.ring_physical_edges(), {}, fixtures.ring_params()
    )
    assert len(design.core_ids) >= 2


def test_min_core_count_is_the_floor_when_feasible() -> None:
    """A design feasible at the floor uses exactly the minimum cores, no more."""
    design = optimize_three_tier_design(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(), {}, DesignParams(min_core_count=3)
    )
    assert len(design.core_ids) == 3


def test_core_tier_grows_past_the_floor_to_seat_more_forced_cores() -> None:
    """With more cores pinned than the floor, the tier grows to seat them all."""
    design = optimize_three_tier_design(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(), {},
        DesignParams(min_core_count=2),
        RoleOverrides(forced_core_ids=frozenset({"P1", "P3", "P5"})),
    )
    assert len(design.core_ids) == 3


def test_no_feasible_design_is_rejected() -> None:
    """No feasible design is rejected when access cannot reach two aggregations."""
    with pytest.raises(ValueError):
        optimize_three_tier_design(TRIANGLE_VERTICES, TRIANGLE, {}, DesignParams(min_core_count=2))


def test_not_enough_core_candidates_is_rejected() -> None:
    """Forcing aggregations can leave too few candidates to be cores."""
    edges = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})
    vertices = [
        pop("a", 0.0, 0.0),
        pop("b", 0.0, 1.0),
        pop("c", 0.0, 2.0),
        access("s1", 0.0, 0.0),
        access("s2", 0.0, 1.0),
    ]
    overrides = RoleOverrides(forced_aggregation_ids=frozenset({"a", "b"}))
    with pytest.raises(ValueError):
        optimize_three_tier_design(vertices, edges, {}, DesignParams(min_core_count=2), overrides)


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


def _symmetric_distances(weights: dict[tuple[str, str], float]) -> dict[str, dict[str, float]]:
    """Build a symmetric all-pairs distance table from undirected pair weights."""
    nodes = {node for pair in weights for node in pair}
    table: dict[str, dict[str, float]] = {node: {node: 0.0} for node in nodes}
    for (left, right), weight in weights.items():
        table[left][right] = weight
        table[right][left] = weight
    return table


# Five fully-connected cores; (c1, c5) is the single longest backbone link.
_FIVE_CORE_DISTANCES = _symmetric_distances({
    ("c1", "c2"): 1.0, ("c1", "c3"): 2.0, ("c1", "c4"): 3.0, ("c1", "c5"): 10.0,
    ("c2", "c3"): 4.0, ("c2", "c4"): 5.0, ("c2", "c5"): 6.0,
    ("c3", "c4"): 7.0, ("c3", "c5"): 8.0,
    ("c4", "c5"): 9.0,
})
_FIVE_CORES = ("c1", "c2", "c3", "c4", "c5")


def _degrees(core_ids: tuple[str, ...], pairs: list[tuple[str, str]]) -> dict[str, int]:
    """Backbone neighbor count of each core over the selected pairs."""
    return {core: sum(1 for pair in pairs if core in pair) for core in core_ids}


def _is_two_edge_connected(core_ids: tuple[str, ...], pairs: list[tuple[str, str]]) -> bool:
    """True if the pairs connect every core and survive losing any one link."""
    ids = set(core_ids)
    edges = set(pairs)
    if len(connected_components(ids, edges)) != 1:
        return False
    return all(len(connected_components(ids, edges - {pair})) == 1 for pair in edges)


def _capped_backbone() -> list[tuple[str, str]]:
    """The degree-3 backbone selected over the five-core mesh (asserted non-None)."""
    pairs = select_core_backbone_pairs(_FIVE_CORES, _FIVE_CORE_DISTANCES, 3)
    assert pairs is not None
    return pairs


def test_core_backbone_caps_degree_at_three() -> None:
    """With a cap of three, no core keeps four backbone neighbors."""
    assert max(_degrees(_FIVE_CORES, _capped_backbone()).values()) <= 3


def test_core_backbone_stays_two_edge_connected() -> None:
    """The capped backbone still survives the loss of any single link."""
    assert _is_two_edge_connected(_FIVE_CORES, _capped_backbone())


def test_core_backbone_drops_the_longest_link() -> None:
    """The single longest core-to-core link is the first dropped under the cap."""
    assert edge_key("c1", "c5") not in _capped_backbone()


def test_core_backbone_is_full_mesh_without_a_cap() -> None:
    """A None cap leaves the full mesh: every core pair keeps a backbone link."""
    pairs = select_core_backbone_pairs(_FIVE_CORES, _FIVE_CORE_DISTANCES, None)
    assert pairs is not None and len(pairs) == 10  # C(5, 2)


def test_core_backbone_unchanged_when_already_within_cap() -> None:
    """Four cores at the cap of three are already a full mesh -- nothing is dropped."""
    four = ("c1", "c2", "c3", "c4")
    pairs = select_core_backbone_pairs(four, _FIVE_CORE_DISTANCES, 3)
    assert pairs is not None and len(pairs) == 6  # C(4, 2): every degree is exactly three


def test_core_backbone_none_when_a_core_pair_is_unreachable() -> None:
    """An unreachable core pair yields no backbone selection."""
    distances = _symmetric_distances({("c1", "c2"): 1.0})
    distances["c1"]["c3"] = math.inf
    distances["c2"]["c3"] = math.inf
    distances["c3"] = {"c3": 0.0, "c1": math.inf, "c2": math.inf}
    assert select_core_backbone_pairs(("c1", "c2", "c3"), distances, 3) is None


_UNIT_MESH_EDGES = physical({
    ("c1", "c2"): 1.0, ("c1", "c3"): 1.0, ("c1", "c4"): 1.0, ("c1", "c5"): 1.0,
    ("c2", "c3"): 1.0, ("c2", "c4"): 1.0, ("c2", "c5"): 1.0,
    ("c3", "c4"): 1.0, ("c3", "c5"): 1.0, ("c4", "c5"): 1.0,
})


def _five_core_mesh_paths(degree_cap: int | None) -> list:
    """Route the five-core backbone over a unit-weight full-mesh graph."""
    adjacency = unit_adjacency(_UNIT_MESH_EDGES)
    distances, predecessors = all_pairs_shortest([pop(c) for c in _FIVE_CORES], adjacency)
    return core_mesh_paths(_FIVE_CORES, distances, predecessors, _UNIT_MESH_EDGES, degree_cap)


def test_core_mesh_paths_route_the_full_mesh_without_a_cap() -> None:
    """Without a cap, routing emits one link per core pair (the full mesh)."""
    assert len(_five_core_mesh_paths(None)) == 10


def test_core_mesh_paths_route_within_the_degree_cap() -> None:
    """Routing under the cap leaves no core with more than three backbone links."""
    pairs = [edge_key(use.source, use.target) for use in _five_core_mesh_paths(3)]
    assert max(_degrees(_FIVE_CORES, pairs).values()) <= 3


def test_vertex_straightness_is_zero_without_reachable_vertices() -> None:
    """Vertex straightness is zero when no other PoP is reachable."""
    assert vertex_straightness("a", {"a": pop("a")}, {}) == 0.0


def test_vertex_straightness_skips_zero_length_hops() -> None:
    """Vertex straightness ignores hops between coincident PoPs."""
    by_id = {"a": pop("a", 0.0, 0.0), "b": pop("b", 0.0, 0.0)}
    assert vertex_straightness("a", by_id, {"b": "a"}) == 0.0


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


# g1 and g2 each reach both cores over vertex-disjoint paths; the cores mesh.
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
    access_vertices = [access(name, lat, lon) for name, (lat, lon) in CLUSTER_ACCESS.items()]
    inputs = _inputs_from_edges(DUAL_IDS, DUAL_EDGES, {"g1", "g2"}, access_vertices, coords)
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
    assert "far" not in cluster_local_heads(members, set(by_id), set(), by_id)


def test_cluster_local_heads_caps_at_two() -> None:
    """A cluster takes at most two heads even when more PoPs are local."""
    members = [access("a", 0.0, 0.0), access("b", 0.0, 0.1), access("c", 0.0, 0.2)]
    by_id = {key: pop(key, 0.0, off) for key, off in (("x", 0.0), ("y", 0.1), ("z", 0.2))}
    assert len(cluster_local_heads(members, set(by_id), set(), by_id)) == 2


def test_cluster_local_heads_prefers_a_selected_facility_over_a_nearer_build() -> None:
    """A local pin becomes a head over closer new builds; reuse beats new-build."""
    members = [access("a", 0.0, 0.0), access("b", 0.0, 0.1), access("c", 0.0, 0.2)]
    by_id = {
        "pin": pop("pin", 0.0, 0.0),   # at the cluster's edge: highest total distance
        "b1": pop("b1", 0.0, 0.1),     # central: lower total distance than the pin
        "b2": pop("b2", 0.0, 0.08),    # also nearer the cluster as a whole than the pin
    }
    heads = cluster_local_heads(members, set(by_id), {"pin"}, by_id)
    assert heads == ["pin", "b1"]      # pin reused first, then the nearest new build


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


def test_enumeration_limit_grows_with_available_memory() -> None:
    """The core sets the search may enumerate scale with the machine's free RAM."""
    params = DesignParams()
    assert enumeration_limit(32 * 10**9, params) > enumeration_limit(16 * 10**9, params)


def test_search_refuses_a_core_space_too_large_for_memory() -> None:
    """The search refuses to enumerate more core sets than RAM can hold."""
    inputs = _inputs_from_edges([], {}, set(), [])
    plan = _plan([f"c{index}" for index in range(40)])
    with pytest.raises(ValueError):
        search_best_design(inputs, DesignParams(min_core_count=20), plan)


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
    """A known PoP name resolves to its vertex id."""
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
    params = DesignParams(forced_core_names=("Colo",), forced_aggregation_names=("Colo",))
    _vertices, _edges, overrides = apply_role_overrides(
        [pop("Colo"), pop("z")], physical({("Colo", "z"): 1.0}), params
    )
    assert "aggr_Colo" in overrides.forced_aggregation_ids


def test_optimize_honors_a_forced_core_override() -> None:
    """A forced-core override is fixed into the selected core tier."""
    design = optimize_three_tier_design(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(), {},
        DesignParams(min_core_count=2), RoleOverrides(forced_core_ids=frozenset({"P3"})),
    )
    assert "P3" in design.core_ids
