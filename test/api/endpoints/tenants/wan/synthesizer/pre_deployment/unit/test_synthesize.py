"""Unit tests for the strength-driven two-tier backbone synthesizer."""

from __future__ import annotations

from dataclasses import replace

import pytest

import fixtures
from synthesizer.input_graph import PhysicalEdge, Vertex, haversine_miles
from synthesizer.model import (
    AccessEdge,
    DesignInputs,
    DesignParams,
    ForcedLinks,
    RoleExclusions,
    RoleOverrides,
    Tuning,
)
from synthesizer.synthesize import (
    all_pairs_shortest,
    assign_access,
    backbone_combination_count,
    backbone_combinations,
    backbone_physically_biconnectable,
    best_design_at_size,
    build_design_for_backbone,
    build_search_plan,
    coverage_candidate_totals,
    compute_eligible_backbone_ids,
    demand_haul_miles,
    enumeration_limit,
    forced_backbone_resilience_error,
    nearest_pop_id,
    search_best_design,
    synthesize_two_tier_design,
    total_memory_bytes,
)
from synthesizer.search_plan import _SearchPlan
from synthesizer.graphs import biconnected_block_membership, build_adjacency
from synthesizer.overrides import apply_role_overrides
from synthesizer.strength import vertex_straightness

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from
access = fixtures.access_vertex


def _cities(*ids: str) -> frozenset[tuple[str, str]]:
    """A data-center-city set covering carrier PoPs built by ``pop`` for these ids."""
    return frozenset((vertex_id, "XX") for vertex_id in ids)


def _inputs_from_edges(
    edge_ids: list[str],
    edges: dict[tuple[str, str], PhysicalEdge],
    eligible: set[str],
    access_vertices: list[Vertex] | None = None,
    coords: dict[str, tuple[float, float]] | None = None,
) -> DesignInputs:
    """Build DesignInputs over a mileage-weighted graph for direct synthesizer tests.

    ``edge_ids`` are the carrier PoPs (the backbone candidates). ``edges`` may also
    wire the demand vertices into the physical graph -- in the two-tier model demand
    homes to the backbone over the physical graph, so any demand that must home is
    given edges here while staying out of ``edge_ids`` (it is not a carrier PoP).
    """
    places = coords or {}
    pops = [pop(vertex_id, *places.get(vertex_id, (0.0, 0.0))) for vertex_id in edge_ids]
    adjacency = build_adjacency(edges)
    distances, predecessors = all_pairs_shortest(pops, adjacency)
    return DesignInputs(
        access_vertices=access_vertices if access_vertices is not None else [],
        carrier_pops=pops,
        physical_edges=edges,
        eligible_backbone_ids=eligible,
        adjacency=adjacency,
        all_distances=distances,
        all_predecessors=predecessors,
        carrier_blocks=biconnected_block_membership(adjacency),
    )


def _plan(
    candidates: list[str],
    strength: dict[str, float] | None = None,
    access_backbone_links: int = 2,
    forced_links: ForcedLinks | None = None,
) -> _SearchPlan:
    """Build a search plan for direct synthesizer tests.

    When no strength map is given, every candidate gets equal strength, so the search
    falls back to its last-mile tie-break.
    """
    strength_by_id = strength if strength is not None else {name: 1.0 for name in candidates}
    return _SearchPlan(
        candidates,
        strength_by_id,
        tuning=Tuning(access_backbone_links=access_backbone_links),
        forced_links=forced_links or ForcedLinks(),
    )


TRIANGLE = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})
TRIANGLE_VERTICES = [pop("a"), pop("b"), pop("c"), access("s", 40.0, -99.0)]


def test_min_backbone_count_below_two_is_rejected() -> None:
    """A minimum backbone count below two is rejected."""
    with pytest.raises(ValueError):
        synthesize_two_tier_design(
            TRIANGLE_VERTICES, TRIANGLE, DesignParams(min_backbone_count=1)
        )


def test_max_backbone_count_below_min_is_rejected() -> None:
    """A maximum backbone count below the minimum is rejected."""
    with pytest.raises(ValueError):
        synthesize_two_tier_design(
            TRIANGLE_VERTICES, TRIANGLE, DesignParams(min_backbone_count=3, max_backbone_count=2)
        )


def test_forced_backbone_exceeding_max_count_is_rejected() -> None:
    """Pinning more backbone nodes than the cap allows is rejected: the pins cannot be dropped."""
    with pytest.raises(ValueError):
        synthesize_two_tier_design(
            TRIANGLE_VERTICES, TRIANGLE,
            DesignParams(min_backbone_count=2, max_backbone_count=2),
            RoleOverrides(forced_backbone_ids=frozenset({"a", "b", "c"})),
        )


def test_unknown_pop_ids_are_rejected() -> None:
    """A physical edge referencing an unknown PoP id is rejected."""
    with pytest.raises(ValueError):
        synthesize_two_tier_design(
            [pop("a"), pop("b")], physical({("a", "c"): 1.0}), DesignParams()
        )


def test_pop_without_edges_is_rejected() -> None:
    """A carrier PoP missing from the physical edge graph is rejected."""
    with pytest.raises(ValueError):
        synthesize_two_tier_design(
            [pop("a"), pop("b"), pop("c")], physical({("a", "b"): 1.0}), DesignParams()
        )


def test_not_enough_eligible_pops_is_rejected() -> None:
    """Too few eligible backbone PoPs (degree >= 2 at a data-center city) is rejected."""
    with pytest.raises(ValueError):
        synthesize_two_tier_design(
            [pop("a"), pop("b")], physical({("a", "b"): 1.0}),
            DesignParams(datacenter_cities=_cities("a", "b")),
        )


def test_synthesizes_ring_to_a_feasible_design() -> None:
    """Synthesizes ring to a feasible design with at least the minimum backbone nodes."""
    design = synthesize_two_tier_design(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(), fixtures.ring_params()
    )
    assert len(design.backbone_ids) >= 2


def test_min_backbone_count_is_the_floor_when_feasible() -> None:
    """A design feasible at the floor uses exactly the minimum backbone nodes, no more."""
    design = synthesize_two_tier_design(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(),
        DesignParams(min_backbone_count=3, datacenter_cities=fixtures.ring_datacenter_cities()),
    )
    assert len(design.backbone_ids) == 3


def test_backbone_grows_past_the_floor_to_seat_more_forced_nodes() -> None:
    """With more nodes pinned than the floor, the backbone grows to seat them all."""
    design = synthesize_two_tier_design(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(),
        DesignParams(min_backbone_count=2, datacenter_cities=fixtures.ring_datacenter_cities()),
        RoleOverrides(forced_backbone_ids=frozenset({"P1", "P3", "P5"})),
    )
    assert len(design.backbone_ids) == 3


def test_no_feasible_design_is_rejected() -> None:
    """No feasible design is rejected when the eligible PoPs cannot mesh as a backbone."""
    edges = physical({("x1", "b1"): 1.0, ("b1", "y1"): 1.0, ("x2", "b2"): 1.0, ("b2", "y2"): 1.0})
    vertices = [pop(name) for name in ("x1", "b1", "y1", "x2", "b2", "y2")]
    with pytest.raises(ValueError):
        synthesize_two_tier_design(
            vertices, edges,
            DesignParams(min_backbone_count=2, datacenter_cities=_cities("b1", "b2")),
        )


def test_honors_a_forced_backbone_override() -> None:
    """A forced-backbone override is fixed into the selected backbone."""
    design = synthesize_two_tier_design(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(),
        DesignParams(min_backbone_count=2, datacenter_cities=fixtures.ring_datacenter_cities()),
        RoleOverrides(forced_backbone_ids=frozenset({"P3"})),
    )
    assert "P3" in design.backbone_ids


# --- compute_eligible_backbone_ids: the data-center gate -------------------------------

def test_eligible_excludes_a_degree_one_spur() -> None:
    """A degree-one PoP can never route redundantly, so it is not eligible."""
    edges = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("c", "a"): 1.0, ("a", "spur"): 1.0})
    pops = [pop(name) for name in ("a", "b", "c", "spur")]
    eligible = compute_eligible_backbone_ids(
        pops, build_adjacency(edges), _cities("a", "b", "c", "spur")
    )
    assert "spur" not in eligible


def test_eligible_includes_a_degree_two_data_center_pop() -> None:
    """A degree-two PoP at a data-center city is an eligible backbone node."""
    edges = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("c", "a"): 1.0})
    pops = [pop(name) for name in ("a", "b", "c")]
    eligible = compute_eligible_backbone_ids(pops, build_adjacency(edges), _cities("a", "b", "c"))
    assert eligible == {"a", "b", "c"}


def test_eligible_excludes_a_pop_off_every_data_center_city() -> None:
    """A strong PoP whose city no colocation provider serves is never eligible."""
    edges = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("c", "a"): 1.0})
    pops = [pop(name) for name in ("a", "b", "c")]
    # Only a and b sit at a data-center city; c is barred despite degree two.
    eligible = compute_eligible_backbone_ids(pops, build_adjacency(edges), _cities("a", "b"))
    assert "c" not in eligible


# --- direct helper coverage ------------------------------------------------------------

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


# A demand site "s" near two backbone PoPs c1 and c2 (which mesh directly). A home is
# the logical demand-to-backbone link, so "s" homes to its two nearest backbone nodes.
DUAL_EDGES = physical(
    {("c1", "c2"): 1.0, ("s", "c1"): 1.0, ("s", "c2"): 1.0}
)


def _dual_inputs(s_coord: tuple[float, float] = (0.0, 0.05)) -> DesignInputs:
    """A two-PoP backbone with one graph-connected demand vertex ``s``."""
    return _inputs_from_edges(
        ["c1", "c2"], DUAL_EDGES, {"c1", "c2"},
        [access("s", *s_coord)], {"c1": (0.0, 0.0), "c2": (0.0, 0.1)},
    )


def _access_link_counts(edges: list[AccessEdge]) -> dict[str, int]:
    """Number of backbone links each demand vertex received."""
    counts: dict[str, int] = {}
    for edge in edges:
        counts[edge.source] = counts.get(edge.source, 0) + 1
    return counts


def test_assign_access_homes_a_demand_vertex_to_two_backbone_nodes() -> None:
    """A demand vertex homes to its two nearest backbone nodes in one pass."""
    result = assign_access(("c1", "c2"), _dual_inputs(), _plan([]))
    assert result is not None and _access_link_counts(result) == {"s": 2}


def test_assign_access_returns_none_when_backbone_smaller_than_links() -> None:
    """With fewer backbone nodes than the homing degree, assignment fails."""
    assert assign_access(("c1",), _dual_inputs(), _plan([], access_backbone_links=2)) is None


def test_assign_access_homes_to_the_configured_count() -> None:
    """A demand vertex homes to exactly the configured number of backbone nodes."""
    triple_edges = physical(
        {
            ("c1", "c2"): 1.0, ("c2", "c3"): 1.0, ("c1", "c3"): 1.0,
            ("s", "c1"): 1.0, ("s", "c2"): 1.0, ("s", "c3"): 1.0,
        }
    )
    inputs = _inputs_from_edges(
        ["c1", "c2", "c3"], triple_edges, {"c1", "c2", "c3"},
        [access("s", 0.0, 0.05)], {"c1": (0.0, 0.0), "c2": (0.0, 0.1), "c3": (0.0, 0.2)},
    )
    result = assign_access(("c1", "c2", "c3"), inputs, _plan([], access_backbone_links=3))
    assert result is not None and _access_link_counts(result) == {"s": 3}


def test_assign_access_leads_with_a_forced_home() -> None:
    """An operator-forced access-backbone link leads a demand vertex's homes."""
    plan = replace(_plan([]), forced_links=ForcedLinks(access=frozenset({("s", "c2")})))
    result = assign_access(("c1", "c2"), _dual_inputs((0.0, 0.0)), plan)
    assert result is not None and {edge.target for edge in result if edge.source == "s"} == {
        "c1", "c2",
    }


def test_build_design_returns_none_without_homing() -> None:
    """build_design_for_backbone returns None when the backbone is too small to home.

    With a single backbone node and a homing degree of two, no demand vertex can reach
    two distinct backbone nodes, so the design is infeasible.
    """
    inputs = _dual_inputs()
    assert build_design_for_backbone(("c1",), inputs, _plan([], access_backbone_links=2)) is None


def test_build_design_returns_none_when_nodes_are_not_meshed() -> None:
    """build_design_for_backbone returns None when a node cannot reach the others."""
    edges = physical(
        {
            ("c1", "g1"): 1.0, ("c2", "g1"): 1.0, ("c1", "g2"): 1.0, ("c2", "g2"): 1.0,
            ("c3", "z"): 1.0, ("s", "c1"): 1.0, ("s", "c2"): 1.0,
        }
    )
    inputs = _inputs_from_edges(
        ["c1", "c2", "c3", "g1", "g2", "z"], edges, {"c1", "c2", "c3"}, [access("s")]
    )
    assert build_design_for_backbone(("c1", "c2", "c3"), inputs, _plan([])) is None


def test_build_design_builds_a_full_design() -> None:
    """build_design_for_backbone assembles a design when the backbone is feasible."""
    design = build_design_for_backbone(("c1", "c2"), _dual_inputs(), _plan([]))
    assert design is not None and set(design.backbone_ids) == {"c1", "c2"}


MESH_EDGES = physical(
    {
        ("a", "b"): 1.0, ("a", "c"): 1.0, ("a", "d"): 1.0,
        ("b", "c"): 1.0, ("b", "d"): 1.0, ("c", "d"): 1.0,
        # The demand sits near every PoP, so any pair are its two nearest homes.
        ("s", "a"): 1.0, ("s", "b"): 1.0, ("s", "c"): 1.0, ("s", "d"): 1.0,
    }
)
# a and b sit beside the demand site; c and d are far. With strengths equal the design
# homing the site to the near pair (a, b) wins on last-mile.
MESH_COORDS = {"a": (0.0, 1.0), "b": (0.0, 2.0), "c": (0.0, 50.0), "d": (0.0, 51.0)}


def _mesh_inputs() -> DesignInputs:
    """A four-PoP full mesh with one graph-connected demand site, for selection tests."""
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
    """Backbone nodes are chosen by strength first, with last-mile only breaking ties."""
    design = best_design_at_size(_mesh_inputs(), _plan(["a", "b", "c", "d"], strength=strength), 2)
    assert design is not None and set(design.backbone_ids) == {"a", "b"}


def test_best_design_at_size_returns_none_when_nothing_feasible() -> None:
    """With no feasible backbone set at a size, the search returns None for that size.

    The two candidate backbone PoPs sit in separate components, so neither can reach the
    other to wire its mesh links and no backbone set of that size is feasible.
    """
    edges = physical({("c1", "x"): 1.0, ("c2", "y"): 1.0})
    inputs = _inputs_from_edges(["c1", "c2", "x", "y"], edges, {"c1", "c2"}, [access("s")])
    assert best_design_at_size(inputs, _plan(["c1", "c2"]), 2) is None


def test_required_backbone_is_fixed_into_every_set() -> None:
    """Required backbone nodes appear in every candidate set the search considers."""
    plan = _plan(["a", "b", "c"], forced_links=ForcedLinks(required_backbone=frozenset({"a"})))
    assert backbone_combinations(plan, 2) == [("a", "b"), ("a", "c")]


def test_backbone_combinations_empty_when_size_below_required() -> None:
    """No backbone set exists when more nodes are required than the size allows."""
    plan = _plan(["a", "b"], forced_links=ForcedLinks(required_backbone=frozenset({"a", "b"})))
    assert backbone_combinations(plan, 1) == []


def test_backbone_combination_count_zero_when_size_below_required() -> None:
    """The count is zero when more nodes are required than the size allows."""
    plan = _plan(["a", "b"], forced_links=ForcedLinks(required_backbone=frozenset({"a", "b"})))
    assert backbone_combination_count(plan, 1) == 0


def test_enumeration_limit_grows_with_available_memory() -> None:
    """The backbone sets the search may enumerate scale with the machine's free RAM."""
    params = DesignParams()
    assert enumeration_limit(32 * 10**9, params) > enumeration_limit(16 * 10**9, params)


def test_total_memory_honors_the_lambda_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Lambda the configured function size (MB) bounds memory, not the host's RAM."""
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_MEMORY_SIZE", "8192")
    assert total_memory_bytes() == 8192 * 1024 * 1024


def test_total_memory_falls_back_to_physical_ram(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off Lambda (no configured size) the installed physical RAM is used."""
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_MEMORY_SIZE", raising=False)
    assert total_memory_bytes() > 0


def test_search_refuses_a_space_too_large_for_memory() -> None:
    """The search refuses to enumerate more backbone sets than RAM can hold."""
    inputs = _inputs_from_edges([], {}, set(), [])
    plan = _plan([f"c{index}" for index in range(40)])
    with pytest.raises(ValueError):
        search_best_design(inputs, DesignParams(min_backbone_count=20), plan)


def test_search_raises_when_no_size_is_feasible() -> None:
    """The search raises when no backbone set of any size yields a feasible design.

    The two candidate backbone PoPs sit in separate components, so they can never reach
    each other to wire their mesh links and no size is feasible.
    """
    edges = physical({("c1", "x"): 1.0, ("c2", "y"): 1.0})
    inputs = _inputs_from_edges(["c1", "c2", "x", "y"], edges, {"c1", "c2"}, [access("s")])
    plan = _plan(["c1", "c2"])
    with pytest.raises(ValueError):
        search_best_design(inputs, DesignParams(min_backbone_count=2), plan)


def test_build_search_plan_ranks_candidates_by_strength() -> None:
    """Every eligible PoP is a backbone candidate, ranked by strength."""
    edges = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})
    inputs = _inputs_from_edges(["a", "b", "c"], edges, {"a", "b", "c"})
    plan = build_search_plan(inputs, {"a", "b", "c"}, RoleOverrides(), DesignParams())
    assert set(plan.backbone_candidates) == {"a", "b", "c"}


def test_demand_haul_miles_reports_worst_and_total_to_nearest_node() -> None:
    """The haul metric sums, and takes the worst of, each demand's nearest-node miles."""
    pops = {
        "node_w": pop("node_w", 40.0, -100.0),
        "node_e": pop("node_e", 40.0, -80.0),
        "near": access("near", 40.0, -99.0),
        "far": access("far", 40.0, -90.0),
    }
    near_miles = haversine_miles(pops["near"], pops["node_w"])
    far_miles = haversine_miles(pops["far"], pops["node_w"])
    result = demand_haul_miles(("node_w", "node_e"), [pops["near"], pops["far"]], pops)
    assert result == pytest.approx((far_miles, near_miles + far_miles))


def test_coverage_candidate_totals_drops_an_infeasible_addition() -> None:
    """A candidate that makes the grown backbone infeasible is dropped from the totals.

    Demand ``s`` homes to c1/c2, but the candidate ``z`` sits in its own component and
    cannot reach a mesh peer, so promoting it yields an unbuildable backbone -- the
    coverage scorer offers it nothing.
    """
    edges = physical(
        {
            ("c1", "c2"): 1.0, ("s", "c1"): 1.0, ("s", "c2"): 1.0, ("z", "y"): 1.0,
        }
    )
    inputs = _inputs_from_edges(
        ["c1", "c2", "z", "y"], edges, {"c1", "c2", "z"}, [access("s", 0.0, 0.05)]
    )
    totals = coverage_candidate_totals(("c1", "c2"), ["z"], inputs, _plan([]), {
        "c1": pop("c1", 0.0, 0.0), "c2": pop("c2", 0.0, 0.1), "z": pop("z", 0.0, 0.2)
    })
    assert not totals


def _far_demand_inputs_plan() -> tuple[DesignInputs, _SearchPlan]:
    """Two central nodes far (by geography) from west/east demand, plus two candidates.

    Shared by the growth and cap tests: a permissive coverage target holds the backbone
    at the two-node floor, while a tight one would grow it to seat a western (cw) and an
    eastern (ce) node that bring the far demand within reach. Every demand vertex wires
    into the graph through the central pair (cc1/cc2), so it always homes; the geography
    is what drives -- or holds -- the coverage growth.
    """
    # cw and ce each wire to both central nodes, so every backbone candidate sits in one
    # biconnected block and the coverage growth (driven by geography, not edges) is what
    # the tests below probe.
    edges = physical(
        {
            ("cc1", "cw"): 1.0, ("cc2", "cw"): 1.0, ("ce", "cc2"): 1.0, ("ce", "cc1"): 1.0,
            ("cc2", "cc1"): 1.0,
            ("aw1", "cc1"): 1.0, ("aw1", "cc2"): 1.0, ("aw2", "cc1"): 1.0, ("aw2", "cc2"): 1.0,
            ("ae1", "cc1"): 1.0, ("ae1", "cc2"): 1.0, ("ae2", "cc1"): 1.0, ("ae2", "cc2"): 1.0,
        }
    )
    coords = {
        "cc1": (44.0, -100.0), "cc2": (44.0, -96.0),
        "cw": (40.0, -118.0), "ce": (40.0, -78.0),
    }
    ids = ["cc1", "cc2", "cw", "ce"]
    access_nodes = [
        access("aw1", 40.0, -120.3), access("aw2", 40.3, -119.7),
        access("ae1", 40.0, -76.3), access("ae2", 40.3, -75.7),
    ]
    inputs = _inputs_from_edges(ids, edges, {"cc1", "cc2", "cw", "ce"}, access_nodes, coords)
    plan = _plan(
        ["cc1", "cc2", "cw", "ce"],
        strength={"cc1": 3.0, "cc2": 3.0, "cw": 1.0, "ce": 1.0},
    )
    return inputs, plan


def test_search_holds_at_the_floor_under_a_permissive_target() -> None:
    """A permissive coverage target leaves the backbone at the strength-chosen floor."""
    inputs, plan = _far_demand_inputs_plan()
    params = DesignParams(
        min_backbone_count=2, datacenter_cities=frozenset(),
        tuning=Tuning(backbone_coverage_target_miles=100_000.0),
    )
    assert search_best_design(inputs, params, plan).backbone_ids == ("cc1", "cc2")


def test_search_grows_past_the_floor_to_cover_far_demand() -> None:
    """Past the floor, nodes are added until far demand is within the coverage target."""
    inputs, plan = _far_demand_inputs_plan()
    params = DesignParams(
        min_backbone_count=2, datacenter_cities=frozenset(),
        tuning=Tuning(backbone_coverage_target_miles=300.0),
    )
    assert set(search_best_design(inputs, params, plan).backbone_ids) == {"cc1", "cc2", "cw", "ce"}


def test_search_exhausts_its_candidates_under_an_unreachable_target() -> None:
    """An unreachable target adds every coverage candidate, then stops when none remain.

    The two extra nodes still leave demand outside an impossibly tight target, so growth
    runs out of candidates rather than meeting coverage or hitting a cap.
    """
    inputs, plan = _far_demand_inputs_plan()
    params = DesignParams(
        min_backbone_count=2, datacenter_cities=frozenset(),
        tuning=Tuning(backbone_coverage_target_miles=1.0),
    )
    assert set(search_best_design(inputs, params, plan).backbone_ids) == {"cc1", "cc2", "cw", "ce"}


def test_max_backbone_count_caps_coverage_growth() -> None:
    """Coverage growth stops once the backbone reaches the configured cap.

    The tight target alone would grow this design to four nodes; capping at three halts
    the growth one node short, leaving exactly the cap.
    """
    inputs, plan = _far_demand_inputs_plan()
    params = DesignParams(
        min_backbone_count=2, max_backbone_count=3, datacenter_cities=frozenset(),
        tuning=Tuning(backbone_coverage_target_miles=300.0),
    )
    assert len(search_best_design(inputs, params, plan).backbone_ids) == 3


def test_search_holds_at_the_floor_when_the_only_candidate_is_infeasible() -> None:
    """Growth stops if the lone candidate would make the grown backbone unbuildable.

    The far demand ``s`` is well past the coverage target, so growth is considered; but
    the only free candidate ``p`` sits in its own graph component and cannot reach a mesh
    peer, so the grown set is infeasible and the backbone holds at the floor.
    """
    edges = physical(
        {
            ("c1", "c2"): 1.0, ("s", "c1"): 1.0, ("s", "c2"): 1.0, ("p", "q"): 1.0,
        }
    )
    coords = {
        "c1": (40.0, -100.0), "c2": (40.0, -99.0), "p": (40.0, -81.0),
    }
    inputs = _inputs_from_edges(
        ["c1", "c2", "p", "q"], edges, {"c1", "c2", "p"}, [access("s", 40.0, -80.5)], coords
    )
    plan = _plan(["c1", "c2", "p"], strength={"c1": 3.0, "c2": 3.0, "p": 1.0})
    params = DesignParams(
        min_backbone_count=2, datacenter_cities=frozenset(),
        tuning=Tuning(backbone_coverage_target_miles=300.0),
    )
    assert search_best_design(inputs, params, plan).backbone_ids == ("c1", "c2")


# --- physical biconnectivity: the search-time city-survivability gate --------------------

# Two triangles -- {a,b,c} and {d,e,f} -- joined only by the single span c-d, so the two
# pockets share no biconnected block: no backbone may straddle them.
_TWO_POCKET_EDGES = physical(
    {
        ("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0, ("c", "d"): 1.0,
        ("d", "e"): 1.0, ("e", "f"): 1.0, ("d", "f"): 1.0,
    }
)
_TWO_POCKET_IDS = ["a", "b", "c", "d", "e", "f"]

# A bowtie -- triangles {a,b,x} and {x,d,e} sharing the cut city x. It is bridgeless (so
# 2-edge-connectable across the lobes) yet x is an articulation point: {a,d} cannot be
# made city-survivable. The case the cable gate passed but the city gate must reject.
_BOWTIE_EDGES = physical(
    {
        ("a", "b"): 1.0, ("b", "x"): 1.0, ("a", "x"): 1.0,
        ("x", "d"): 1.0, ("d", "e"): 1.0, ("x", "e"): 1.0,
    }
)
_BOWTIE_IDS = ["a", "b", "x", "d", "e"]


def _two_pocket_inputs() -> DesignInputs:
    """Inputs over two fiber pockets joined by a single bridge span."""
    return _inputs_from_edges(_TWO_POCKET_IDS, _TWO_POCKET_EDGES, set(_TWO_POCKET_IDS))


def _bowtie_inputs() -> DesignInputs:
    """Inputs over a bowtie: two triangles sharing one cut city."""
    return _inputs_from_edges(_BOWTIE_IDS, _BOWTIE_EDGES, set(_BOWTIE_IDS))


def test_physically_biconnectable_within_one_block() -> None:
    """Two nodes sharing one biconnected block can be wired into a city-survivable mesh."""
    assert backbone_physically_biconnectable(("a", "b"), _two_pocket_inputs()) is True


def test_not_physically_biconnectable_across_a_bridge() -> None:
    """Two nodes split by a single span share no block, so they are rejected."""
    assert backbone_physically_biconnectable(("a", "d"), _two_pocket_inputs()) is False


def test_not_physically_biconnectable_across_a_cut_city() -> None:
    """Two nodes either side of a cut city are rejected though no single cable splits them."""
    assert backbone_physically_biconnectable(("a", "d"), _bowtie_inputs()) is False


def test_physically_biconnectable_within_one_bowtie_lobe() -> None:
    """Two nodes in the same bowtie lobe share that lobe's block, so they pass."""
    assert backbone_physically_biconnectable(("a", "b"), _bowtie_inputs()) is True


def test_not_biconnectable_with_no_backbone_nodes() -> None:
    """An empty backbone shares no block, so the gate rejects it."""
    assert backbone_physically_biconnectable((), _bowtie_inputs()) is False


def test_forced_resilience_error_for_forced_nodes_split_across_pockets() -> None:
    """Forced nodes in different pockets can never form a resilient design."""
    assert forced_backbone_resilience_error(
        frozenset({"a", "d"}), _two_pocket_inputs(), 2
    ) is not None


def _triangle_inputs() -> DesignInputs:
    """Inputs over a single 2-edge-connected triangle pocket of three eligible PoPs."""
    return _inputs_from_edges(["a", "b", "c"], TRIANGLE, {"a", "b", "c"})


def test_forced_resilience_error_for_a_pocket_too_small_for_the_floor() -> None:
    """A forced node whose block cannot seat the minimum backbone count is rejected.

    The forced node's pocket holds only its three triangle peers, fewer than the floor of
    five, even though other eligible nodes sit in the graph's other pocket.
    """
    assert forced_backbone_resilience_error(frozenset({"a"}), _two_pocket_inputs(), 5) is not None


def test_forced_resilience_error_none_for_a_healthy_forced_node() -> None:
    """A forced node in a pocket large enough for the floor raises nothing."""
    assert forced_backbone_resilience_error(frozenset({"a"}), _triangle_inputs(), 2) is None


def test_forced_resilience_error_none_without_forced_nodes() -> None:
    """With no forced nodes there is nothing to check, so no error."""
    assert forced_backbone_resilience_error(frozenset(), _triangle_inputs(), 2) is None


def test_synthesize_rejects_forced_nodes_split_across_pockets() -> None:
    """Synthesis fails loudly when forced nodes straddle a single-fiber cut."""
    vertices = [pop(name) for name in _TWO_POCKET_IDS]
    params = DesignParams(
        min_backbone_count=2,
        forced_backbone_names=("a", "d"),
        datacenter_cities=_cities(*_TWO_POCKET_IDS),
    )
    pinned, edges, overrides = apply_role_overrides(vertices, _TWO_POCKET_EDGES, params)
    with pytest.raises(ValueError):
        synthesize_two_tier_design(pinned, edges, params, overrides)


# --- overrides: data-center gate on forced pins ----------------------------------------

def test_apply_role_overrides_resolves_a_forced_backbone_pin() -> None:
    """A forced backbone name at a data-center city resolves to its vertex id."""
    params = DesignParams(forced_backbone_names=("a",), datacenter_cities=_cities("a"))
    _vertices, _edges, overrides = apply_role_overrides(
        [pop("a"), pop("b")], physical({("a", "b"): 1.0}), params
    )
    assert overrides.forced_backbone_ids == frozenset({"a"})


def test_apply_role_overrides_rejects_a_forced_pin_off_a_data_center_city() -> None:
    """A forced backbone pin at a city no provider serves is rejected -- the gate is absolute."""
    params = DesignParams(forced_backbone_names=("a",), datacenter_cities=frozenset())
    with pytest.raises(ValueError):
        apply_role_overrides([pop("a"), pop("b")], physical({("a", "b"): 1.0}), params)


def test_apply_role_overrides_rejects_a_forced_and_prohibited_pop() -> None:
    """A PoP both forced onto and barred from the backbone is rejected."""
    params = DesignParams(
        forced_backbone_names=("a",),
        exclusions=RoleExclusions(prohibited_backbone_names=("a",)),
        datacenter_cities=_cities("a"),
    )
    with pytest.raises(ValueError):
        apply_role_overrides([pop("a"), pop("b")], physical({("a", "b"): 1.0}), params)
