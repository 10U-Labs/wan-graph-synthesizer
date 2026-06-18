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
    ForcedLinks,
    Vertex,
    PathUse,
    PhysicalEdge,
    RoleOverrides,
    Tuning,
    edge_key,
    haversine_miles,
)
from wan_designer.backbone import (
    BackboneConstraints,
    core_mesh_paths,
    select_core_backbone_pairs,
)
from wan_designer.optimize import (
    aggregation_core_paths,
    aggregation_haul_miles,
    all_pairs_shortest,
    assign_access,
    best_design_at_size,
    build_design_for_cores,
    build_search_plan,
    cluster_diameter,
    cluster_local_heads,
    complete_homes,
    core_combination_count,
    core_combinations,
    cores_mesh,
    cores_reachable_avoiding,
    dual_homes_to_pair,
    effective_forced_aggregations,
    enumeration_limit,
    feasible_aggregation_ids,
    feasible_colocation_twins,
    nearest_pop_id,
    prune_unused_aggregations,
    optimize_three_tier_design,
    search_best_design,
    _AggregationPlan,
    _SearchPlan,
)
from wan_designer.parsing import build_adjacency
from wan_designer.overrides import (
    apply_role_overrides,
    colocated_twin,
    colocation_edges,
    materialize_selected_colocation_twins,
    reject_override_conflicts,
    resolve_pinned_ids,
)
from wan_designer.strength import vertex_straightness

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
    """Build DesignInputs over a mileage-weighted graph for direct optimizer tests."""
    places = coords or {}
    pops = [pop(vertex_id, *places.get(vertex_id, (0.0, 0.0))) for vertex_id in edge_ids]
    adjacency = build_adjacency(edges)
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
    access_aggregation_links: int = 2,
) -> _SearchPlan:
    """Build a search plan for direct optimizer tests."""
    return _SearchPlan(
        candidates,
        _AggregationPlan(frozenset(forced or set())),
        strength or {},
        clusters=clusters or [],
        tuning=Tuning(access_aggregation_links=access_aggregation_links),
    )


def _required_plan(candidates: list[str], required: set[str]) -> _SearchPlan:
    """Build a search plan with required cores, for core-combination tests."""
    return _SearchPlan(
        candidates, _AggregationPlan(), {},
        forced_links=ForcedLinks(required_cores=frozenset(required)),
    )


TRIANGLE = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})
TRIANGLE_VERTICES = [pop("a"), pop("b"), pop("c"), access("s", 40.0, -99.0)]


def test_min_core_count_below_two_is_rejected() -> None:
    """A minimum core count below two is rejected."""
    with pytest.raises(ValueError):
        optimize_three_tier_design(TRIANGLE_VERTICES, TRIANGLE, {}, DesignParams(min_core_count=1))


def test_max_core_count_below_min_is_rejected() -> None:
    """A maximum core count below the minimum is rejected."""
    with pytest.raises(ValueError):
        optimize_three_tier_design(
            TRIANGLE_VERTICES, TRIANGLE, {}, DesignParams(min_core_count=3, max_core_count=2)
        )


def test_forced_cores_exceeding_max_core_count_is_rejected() -> None:
    """Pinning more cores than the cap allows is rejected: the pins cannot be dropped."""
    with pytest.raises(ValueError):
        optimize_three_tier_design(
            TRIANGLE_VERTICES, TRIANGLE, {},
            DesignParams(min_core_count=2, max_core_count=2),
            RoleOverrides(forced_core_ids=frozenset({"a", "b", "c"})),
        )


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
    """No feasible design is rejected when the eligible PoPs cannot mesh as cores."""
    edges = physical({("x1", "b1"): 1.0, ("b1", "y1"): 1.0, ("x2", "b2"): 1.0, ("b2", "y2"): 1.0})
    vertices = [pop(name) for name in ("x1", "b1", "y1", "x2", "b2", "y2")]
    with pytest.raises(ValueError):
        optimize_three_tier_design(vertices, edges, {}, DesignParams(min_core_count=2))


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
    _distance, paths = aggregation_core_paths("S", ("C1", "C2"), build_adjacency(edges), edges)
    assert not paths


def test_aggregation_homes_to_the_two_nearest_cores_by_miles() -> None:
    """An aggregation routes to the two cores nearest in miles, not in hops.

    ``C3`` is one hop away but 100 miles off; ``C1``/``C2`` are two hops but two
    miles each. Mileage routing picks the near pair and skips the far single hop --
    a hop-count metric would instead keep the single-hop ``C3``.
    """
    edges = physical({
        ("S", "C3"): 100.0,
        ("S", "A"): 1.0, ("A", "C1"): 1.0,
        ("S", "B"): 1.0, ("B", "C2"): 1.0,
    })
    _distance, paths = aggregation_core_paths(
        "S", ("C1", "C2", "C3"), build_adjacency(edges), edges
    )
    assert {use.target for use in paths} == {"C1", "C2"}


def test_core_mesh_paths_empty_when_cores_disconnected() -> None:
    """Core mesh paths empty when cores disconnected."""
    edges = physical({("a", "b"): 1.0, ("c", "d"): 1.0})
    adjacency = build_adjacency(edges)
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


# Five fully-connected cores with distinct finite inter-core distances.
_FIVE_CORE_DISTANCES = _symmetric_distances({
    ("c1", "c2"): 1.0, ("c1", "c3"): 2.0, ("c1", "c4"): 3.0, ("c1", "c5"): 10.0,
    ("c2", "c3"): 4.0, ("c2", "c4"): 5.0, ("c2", "c5"): 6.0,
    ("c3", "c4"): 7.0, ("c3", "c5"): 8.0,
    ("c4", "c5"): 9.0,
})
_FIVE_CORES = ("c1", "c2", "c3", "c4", "c5")


def _full_mesh(removed: frozenset[tuple[str, str]] = frozenset()) -> list[tuple[str, str]]:
    """The core backbone over the five-core mesh, minus ``removed`` (asserted reachable)."""
    pairs = select_core_backbone_pairs(_FIVE_CORES, _FIVE_CORE_DISTANCES, removed)
    assert pairs is not None
    return pairs


def test_core_backbone_is_the_full_mesh() -> None:
    """Every core pair gets a backbone link: the full mesh of C(5, 2) = 10 links."""
    assert len(_full_mesh()) == 10


def test_core_backbone_omits_a_removed_pair() -> None:
    """An operator-pruned core-core pair gets no backbone link."""
    assert edge_key("c1", "c5") not in _full_mesh(frozenset({edge_key("c1", "c5")}))


def test_core_backbone_keeps_the_other_pairs_when_one_is_removed() -> None:
    """Pruning one pair drops exactly that link: nine of the ten mesh links remain."""
    assert len(_full_mesh(frozenset({edge_key("c1", "c5")}))) == 9


def test_core_backbone_none_when_a_kept_core_pair_is_unreachable() -> None:
    """A kept core pair unreachable over the carrier graph yields no backbone selection."""
    distances = _symmetric_distances({("c1", "c2"): 1.0})
    assert select_core_backbone_pairs(("c1", "c2", "c3"), distances) is None


_UNIT_MESH_EDGES = physical({
    ("c1", "c2"): 1.0, ("c1", "c3"): 1.0, ("c1", "c4"): 1.0, ("c1", "c5"): 1.0,
    ("c2", "c3"): 1.0, ("c2", "c4"): 1.0, ("c2", "c5"): 1.0,
    ("c3", "c4"): 1.0, ("c3", "c5"): 1.0, ("c4", "c5"): 1.0,
})


def _five_core_mesh_paths(removed: frozenset[tuple[str, str]] = frozenset()) -> list[PathUse]:
    """Route the five-core backbone over a mileage-weighted full-mesh graph."""
    adjacency = build_adjacency(_UNIT_MESH_EDGES)
    distances, predecessors = all_pairs_shortest([pop(c) for c in _FIVE_CORES], adjacency)
    return core_mesh_paths(
        _FIVE_CORES, distances, predecessors, _UNIT_MESH_EDGES, BackboneConstraints(removed)
    )


def test_core_mesh_paths_route_the_full_mesh() -> None:
    """The backbone routes one path per core pair: the full mesh of ten links."""
    assert len(_five_core_mesh_paths()) == 10


def test_core_mesh_paths_omit_a_removed_pair() -> None:
    """An operator-pruned pair gets no routed core-mesh path."""
    routed = _five_core_mesh_paths(frozenset({edge_key("c1", "c2")}))
    assert edge_key("c1", "c2") not in {edge_key(use.source, use.target) for use in routed}


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


def test_cores_reachable_avoiding_excludes_the_blocked_pop() -> None:
    """Reachability from a PoP's neighbors never passes back through the PoP itself."""
    adjacency = build_adjacency(physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("c", "d"): 1.0}))
    assert cores_reachable_avoiding("b", adjacency) == {"a", "c", "d"}


def test_cores_reachable_avoiding_cannot_cross_a_cut_vertex() -> None:
    """With the only connector removed, the spokes reach nothing past it."""
    adjacency = build_adjacency(physical({("hub", "l1"): 1.0, ("hub", "l2"): 1.0}))
    assert cores_reachable_avoiding("hub", adjacency) == {"l1", "l2"}


def _twin_plan(reach: set[str]) -> _SearchPlan:
    """A plan offering ``c1``'s co-located twin, reaching ``reach`` around ``c1``."""
    aggregations = _AggregationPlan(
        twin_to_core={"aggr_c1": "c1"}, reach_avoiding={"c1": reach}
    )
    return _SearchPlan([], aggregations, {})


def test_feasible_colocation_twins_offers_a_reachable_core_twin() -> None:
    """A selected core that can reach another core around itself offers its twin."""
    assert feasible_colocation_twins(("c1", "c2"), _twin_plan({"c2"})) == {"aggr_c1"}


def test_feasible_colocation_twins_skips_an_unselected_cores_twin() -> None:
    """A core that is not in the set offers no twin, even if it could reach around."""
    assert feasible_colocation_twins(("c2", "c3"), _twin_plan({"c2"})) == set()


def test_feasible_colocation_twins_skips_a_twin_that_loses_redundancy() -> None:
    """A selected core whose only reach-around lands off the core set offers no twin."""
    assert feasible_colocation_twins(("c1", "c2"), _twin_plan({"x"})) == set()


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
    adjacency = build_adjacency(edges)
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


# Three aggregations, each dual-homing to both cores, for the configurable-count check.
TRIPLE_EDGES = physical(
    {
        ("g1", "c1"): 1.0, ("g1", "c2"): 1.0,
        ("g2", "c1"): 1.0, ("g2", "c2"): 1.0,
        ("g3", "c1"): 1.0, ("g3", "c2"): 1.0, ("c1", "c2"): 1.0,
    }
)


def _access_link_counts(edges: list[AccessEdge]) -> dict[str, int]:
    """Number of aggregation links each access vertex received."""
    counts: dict[str, int] = {}
    for edge in edges:
        counts[edge.source] = counts.get(edge.source, 0) + 1
    return counts


def test_assign_access_homes_to_the_configured_count() -> None:
    """Each access vertex homes to exactly the configured number of aggregations."""
    coords = {"g1": (0.0, 0.0), "g2": (0.0, 0.05), "g3": (0.0, 0.1)}
    access_vertices = [access(name, lat, lon) for name, (lat, lon) in CLUSTER_ACCESS.items()]
    inputs = _inputs_from_edges(
        ["g1", "g2", "g3", "c1", "c2"], TRIPLE_EDGES, {"g1", "g2", "g3"}, access_vertices, coords
    )
    plan = _plan([], clusters=[list(CLUSTER_ACCESS)], access_aggregation_links=3)
    result = assign_access(("c1", "c2"), inputs, plan)
    assert result is not None and _access_link_counts(result[0]) == {
        name: 3 for name in CLUSTER_ACCESS
    }


def test_assign_access_requires_the_configured_count_of_feasible_aggregations() -> None:
    """With fewer feasible aggregations than the configured count, assignment fails."""
    coords = {"g1": (0.0, 0.0), "g2": (0.0, 0.05)}
    access_vertices = [access(name, lat, lon) for name, (lat, lon) in CLUSTER_ACCESS.items()]
    inputs = _inputs_from_edges(
        ["g1", "g2", "c1", "c2"], DUAL_EDGES, {"g1", "g2"}, access_vertices, coords
    )
    plan = _plan([], clusters=[list(CLUSTER_ACCESS)], access_aggregation_links=3)
    assert assign_access(("c1", "c2"), inputs, plan) is None


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


def test_cluster_local_heads_caps_at_the_configured_count() -> None:
    """A cluster takes up to the configured number of heads when more PoPs are local."""
    members = [access("a", 0.0, 0.0), access("b", 0.0, 0.1), access("c", 0.0, 0.2)]
    by_id = {key: pop(key, 0.0, off) for key, off in (("x", 0.0), ("y", 0.1), ("z", 0.2))}
    assert len(cluster_local_heads(members, set(by_id), set(), by_id, count=3)) == 3


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
    "selected, feasible, expected",
    [
        ({"x", "y"}, {"x", "y", "z"}, {"x", "y"}),  # reuse fills both homes
        (set(), {"x", "y"}, {"x", "y"}),  # nothing to reuse: build two
        (set(), {"x"}, {"x"}),  # only one reachable: returns one
    ],
)
def test_complete_homes(
    selected: set[str], feasible: set[str], expected: set[str]
) -> None:
    """Homes prefer reuse, then build, toward the requested count."""
    result = complete_homes(access("s", 0.0, 0.0), selected, feasible, HOMES_POPS)
    assert set(result) == expected


def test_complete_homes_fills_to_the_configured_count() -> None:
    """complete_homes reaches the configured number of homes when enough are reachable."""
    result = complete_homes(
        access("s", 0.0, 0.0), {"x", "y"}, {"x", "y", "z"}, HOMES_POPS, count=3
    )
    assert set(result) == {"x", "y", "z"}


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


def test_reject_override_conflicts_rejects_prohibiting_a_forced_aggregation() -> None:
    """A PoP both forced as and prohibited from being an aggregation is rejected."""
    with pytest.raises(ValueError):
        reject_override_conflicts(set(), {"a"}, set(), {"a"})


def test_reject_override_conflicts_allows_prohibiting_a_forced_core() -> None:
    """Forcing a PoP as a core while barring it from the aggregation tier is allowed."""
    reject_override_conflicts({"a"}, set(), set(), {"a"})


def test_apply_role_overrides_resolves_prohibited_aggregations() -> None:
    """A prohibited-aggregation name resolves to its vertex id in the overrides."""
    params = DesignParams(prohibited_aggregation_names=("P",))
    _vertices, _edges, overrides = apply_role_overrides(
        [pop("P"), pop("z")], physical({("P", "z"): 1.0}), params
    )
    assert overrides.prohibited_aggregation_ids == frozenset({"P"})


def test_apply_role_overrides_rejects_an_unknown_prohibited_name() -> None:
    """An unknown prohibited-aggregation PoP name is rejected, not silently dropped."""
    params = DesignParams(prohibited_aggregation_names=("Nowhere",))
    with pytest.raises(ValueError):
        apply_role_overrides([pop("P")], physical({("P", "z"): 1.0}), params)


def test_build_search_plan_keeps_a_prohibited_pop_as_a_core_candidate() -> None:
    """A prohibited PoP stays a core candidate but is offered no aggregation twin."""
    edges = physical({("p", "q"): 1.0, ("q", "c"): 1.0, ("p", "c"): 1.0})
    inputs = _inputs_from_edges(["p", "q", "c"], edges, {"q", "c"})  # p barred from aggregation
    plan = build_search_plan(
        inputs, {"p", "q", "c"}, _AggregationPlan(), RoleOverrides(), DesignParams()
    )
    assert "p" in plan.core_candidates
    assert "aggr_p" not in plan.aggregations.twin_to_core
    assert "aggr_q" in plan.aggregations.twin_to_core


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


def test_optimize_lets_a_core_also_serve_as_an_aggregation() -> None:
    """On a small graph the search dual-roles a core through its co-located twin."""
    design = optimize_three_tier_design(
        TRIANGLE_VERTICES, TRIANGLE, {}, DesignParams(min_core_count=2)
    )
    twinned = {agg[len("aggr_"):] for agg in design.aggregation_ids if agg.startswith("aggr_")}
    assert twinned & set(design.core_ids)


def test_optimize_keeps_a_single_twin_for_an_operator_colocation() -> None:
    """An operator co-location yields one twin; the auto pass never adds a second."""
    params = DesignParams(
        min_core_count=2, forced_core_names=("P0",), forced_aggregation_names=("P0",)
    )
    vertices, edges, overrides = apply_role_overrides(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(), params
    )
    design = optimize_three_tier_design(vertices, edges, {}, params, overrides)
    assert design.aggregation_ids.count("aggr_P0") == 1


def _bare_design(core_ids: tuple[str, ...], aggregation_ids: tuple[str, ...]) -> Design:
    """A minimal design carrying only the tier ids the twin materializer reads."""
    return Design(core_ids, aggregation_ids, (), [], set(), [], DesignMetrics(0.0, 0.0, 0.0))


def test_materialize_selected_colocation_twins_stands_up_a_seated_twin() -> None:
    """A seated co-located twin gains its vertex so validation and the payload see it."""
    design = _bare_design(("c1",), ("aggr_c1",))
    vertices, _edges = materialize_selected_colocation_twins(
        [pop("c1")], physical({("c1", "c2"): 1.0}), design
    )
    assert any(vertex.id == "aggr_c1" for vertex in vertices)


def test_materialize_selected_colocation_twins_skips_an_existing_twin() -> None:
    """An operator-built twin already in the graph is not stood up a second time."""
    design = _bare_design(("c1",), ("aggr_c1",))
    vertices, _edges = materialize_selected_colocation_twins(
        [pop("c1"), colocated_twin(pop("c1"))], physical({("c1", "c2"): 1.0}), design
    )
    assert sum(1 for vertex in vertices if vertex.id == "aggr_c1") == 1


def test_materialize_selected_colocation_twins_ignores_a_core_without_a_twin() -> None:
    """A core the search did not dual-role gets no co-located twin vertex."""
    design = _bare_design(("c1",), ())
    vertices, _edges = materialize_selected_colocation_twins(
        [pop("c1")], physical({("c1", "c2"): 1.0}), design
    )
    assert all(not vertex.id.startswith("aggr_") for vertex in vertices)


def test_optimize_honors_a_forced_core_override() -> None:
    """A forced-core override is fixed into the selected core tier."""
    design = optimize_three_tier_design(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(), {},
        DesignParams(min_core_count=2), RoleOverrides(forced_core_ids=frozenset({"P3"})),
    )
    assert "P3" in design.core_ids


def test_effective_forced_aggregations_returns_operator_pins() -> None:
    """The only hard-required aggregations are the operator's pins."""
    assert effective_forced_aggregations(_plan([], forced={"op"})) == {"op"}


def test_build_search_plan_excludes_forced_aggregations_from_cores() -> None:
    """A forced aggregation -- like a forced installation twin -- is never a core candidate."""
    edges = physical({("fac", "p"): 1.0, ("p", "c"): 1.0, ("fac", "c"): 1.0})
    inputs = _inputs_from_edges(["fac", "p", "c"], edges, {"fac", "p", "c"})
    plan = build_search_plan(
        inputs, {"fac", "p", "c"}, _AggregationPlan(frozenset({"fac"})), RoleOverrides(),
        DesignParams(),
    )
    assert "fac" not in plan.core_candidates


def test_prune_unused_aggregations_drops_a_zero_access_anchor() -> None:
    """A seated aggregation that no access vertex homes to is dropped from the tier."""
    edges = [AccessEdge("a1", "used", 10.0)]
    assert prune_unused_aggregations({"used", "unused"}, edges, frozenset()) == {"used"}


def test_prune_unused_aggregations_keeps_an_operator_pin_without_access() -> None:
    """An operator-forced pin is retained even when no access vertex homes to it."""
    edges = [AccessEdge("a1", "used", 10.0)]
    result = prune_unused_aggregations({"used", "pinned"}, edges, frozenset({"pinned"}))
    assert result == {"used", "pinned"}


def test_aggregation_haul_miles_reports_the_worst_and_total_to_nearest_core() -> None:
    """The haul metric sums, and takes the worst of, each aggregation's nearest-core miles."""
    pops = {
        "core_w": pop("core_w", 40.0, -100.0),
        "core_e": pop("core_e", 40.0, -80.0),
        "near": pop("near", 40.0, -99.0),
        "far": pop("far", 40.0, -90.0),
    }
    near_miles = haversine_miles(pops["near"], pops["core_w"])
    far_miles = haversine_miles(pops["far"], pops["core_w"])
    result = aggregation_haul_miles(("core_w", "core_e"), ("near", "far"), pops)
    assert result == pytest.approx((far_miles, near_miles + far_miles))


def _far_demand_inputs_plan() -> tuple[DesignInputs, _SearchPlan]:
    """Two central cores ~1000 mi from west/east demand, with two coverage candidates.

    Shared by the growth and cap tests: a permissive coverage target holds the tier
    at the two-core floor, while a tight one would grow it to seat a western (cw) and
    an eastern (ce) core that bring the far demand within reach.
    """
    edges = physical(
        {
            ("cc1", "cw"): 1.0, ("cw", "aw"): 1.0, ("aw", "ae"): 1.0,
            ("ae", "ce"): 1.0, ("ce", "cc2"): 1.0, ("cc2", "cc1"): 1.0,
        }
    )
    coords = {
        "cc1": (44.0, -100.0), "cc2": (44.0, -96.0),
        "cw": (40.0, -118.0), "ce": (40.0, -78.0),
        "aw": (40.0, -120.0), "ae": (40.0, -76.0),
    }
    ids = ["cc1", "cc2", "cw", "ce", "aw", "ae"]
    access_nodes = [
        access("aw1", 40.0, -120.3), access("aw2", 40.3, -119.7),
        access("ae1", 40.0, -76.3), access("ae2", 40.3, -75.7),
    ]
    inputs = _inputs_from_edges(ids, edges, {"aw", "ae"}, access_nodes, coords)
    plan = _plan(
        ["cc1", "cc2", "cw", "ce"],
        strength={"cc1": 3.0, "cc2": 3.0, "cw": 1.0, "ce": 1.0},
        clusters=[["aw1", "aw2"], ["ae1", "ae2"]],
    )
    return inputs, plan


def test_search_grows_cores_past_the_floor_to_cover_far_demand() -> None:
    """Past the floor, cores are added until far demand is within the coverage target."""
    inputs, plan = _far_demand_inputs_plan()

    def cores(target_miles: float) -> tuple[str, ...]:
        params = DesignParams(
            min_core_count=2, tuning=Tuning(core_coverage_target_miles=target_miles)
        )
        return search_best_design(inputs, params, plan).core_ids

    assert (cores(100_000.0), set(cores(300.0))) == (
        ("cc1", "cc2"),
        {"cc1", "cc2", "cw", "ce"},
    )


def test_max_core_count_caps_coverage_growth() -> None:
    """Coverage growth stops once the core tier reaches the configured cap.

    The tight target alone would grow this design to four cores; capping at three
    halts the growth one core short, leaving exactly the cap.
    """
    inputs, plan = _far_demand_inputs_plan()
    params = DesignParams(
        min_core_count=2, max_core_count=3, tuning=Tuning(core_coverage_target_miles=300.0)
    )
    assert len(search_best_design(inputs, params, plan).core_ids) == 3


def test_search_holds_at_the_floor_when_the_only_candidate_would_strand_demand() -> None:
    """Growth stops if adding the lone candidate drops the aggregation tier below two.

    Aggregations ``agg`` and ``p`` both serve the far eastern access, but ``p`` is also
    the only free core candidate; promoting it would leave a single aggregation, so the
    grown set is infeasible and the tier holds at the floor despite the long haul.
    """
    edges = physical(
        {
            ("c1", "c2"): 1.0, ("agg", "c1"): 1.0, ("agg", "c2"): 1.0,
            ("p", "c1"): 1.0, ("p", "c2"): 1.0,
        }
    )
    coords = {
        "c1": (40.0, -100.0), "c2": (40.0, -99.0),
        "agg": (40.0, -80.0), "p": (40.0, -81.0),
    }
    inputs = _inputs_from_edges(
        ["c1", "c2", "agg", "p"], edges, {"agg", "p"}, [access("s", 40.0, -80.5)], coords
    )
    plan = _plan(["c1", "c2", "p"], strength={"c1": 3.0, "c2": 3.0, "p": 1.0})
    params = DesignParams(min_core_count=2, tuning=Tuning(core_coverage_target_miles=300.0))
    assert search_best_design(inputs, params, plan).core_ids == ("c1", "c2")
