"""Unit tests for the strength-driven two-tier backbone synthesizer."""

from __future__ import annotations

from dataclasses import replace

import pytest

import fixtures
from fixtures import (
    TRIANGLE,
    TWO_POCKET_EDGES,
    TWO_POCKET_IDS,
    design_inputs_from_edges,
    search_plan,
)
from synthesizer.input_graph import edge_key
from synthesizer.model import (
    Design,
    DesignInputs,
    DesignMetrics,
    DesignParams,
    ForcedLinks,
    RoleExclusions,
    RoleOverrides,
    Tuning,
)
from synthesizer.synthesize import (
    backbone_combination_count,
    backbone_combinations,
    best_design_at_size,
    build_search_plan,
    convergence_promotion_ids,
    compute_eligible_backbone_ids,
    enumeration_limit,
    search_best_design,
    synthesize_two_tier_design,
    total_memory_bytes,
)
from synthesizer.search_plan import _SearchPlan
from synthesizer.graphs import build_adjacency
from synthesizer.overrides import apply_role_overrides
from synthesizer.strength import vertex_straightness

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from
access = fixtures.access_vertex
TRIANGLE_VERTICES = [pop("a"), pop("b"), pop("c"), access("s", 40.0, -99.0)]


def _cities(*ids: str) -> frozenset[tuple[str, str]]:
    """A data-center-city set covering carrier PoPs built by ``pop`` for these ids."""
    return frozenset((vertex_id, "XX") for vertex_id in ids)


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


def test_synthesize_promotes_a_data_center_convergence_hub() -> None:
    """A transit PoP carrying >= 3 of the design's lines at a data-center city is seated.

    Drives the full promote-then-redraw loop: the first design leaves the centre as a
    transit node, the convergence pass forces it in, and the redraw seats it.
    """
    design = fixtures.convergence_hub_artifacts().design
    assert "hub_dc" in design.backbone_ids


_UNPROMOTED_CONVERGENCE = fixtures.convergence_hub_artifacts(promote_convergences=False).design


def test_promotion_disabled_leaves_a_convergence_hub_transit() -> None:
    """With promotion off, a >= 3-line data-center hub is left transit, not seated."""
    assert "hub_dc" not in _UNPROMOTED_CONVERGENCE.backbone_ids


_CAPPED_CONVERGENCE = fixtures.convergence_hub_artifacts(max_backbone_count=4).design


def test_backbone_cap_blocks_a_convergence_promotion() -> None:
    """A backbone cap with no spare slot blocks the promotion -- the centre stays transit."""
    assert "hub_dc" not in _CAPPED_CONVERGENCE.backbone_ids


def test_capped_convergence_design_fills_its_backbone_budget() -> None:
    """The capped design still seats exactly its backbone-count budget."""
    assert len(_CAPPED_CONVERGENCE.backbone_ids) == 4


# --- compute_eligible_backbone_ids: the data-center gate -------------------------------

def test_eligible_excludes_a_degree_one_spur() -> None:
    """A degree-one PoP can never path redundantly, so it is not eligible."""
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


# --- convergence_promotion_ids: per-design data-center hub promotion -------------------

def _design(
    backbone_ids: tuple[str, ...],
    physical_edge_keys: set[tuple[str, str]],
) -> Design:
    """A Design carrying only the fields the convergence pass reads."""
    return Design(
        backbone_ids=backbone_ids,
        transit_ids=(),
        access_edges=[],
        physical_edge_keys=physical_edge_keys,
        path_uses=[],
        metrics=DesignMetrics(0.0, 0.0, 0.0),
    )


def test_convergence_promotes_a_data_center_transit_hub() -> None:
    """A non-backbone data-center PoP carrying >= 3 of the design's lines is promoted."""
    # hub carries four of the design's drawn edges; b1/b2 are the seated backbone.
    keys = {edge_key("hub", n) for n in ("b1", "b2", "x", "y")}
    design = _design(("b1", "b2"), keys)
    pops = [pop(name) for name in ("hub", "b1", "b2", "x", "y")]
    promoted = convergence_promotion_ids(design, pops, _cities("hub", "x", "y"))
    assert promoted == {"hub"}


def test_convergence_skips_a_two_line_crossing() -> None:
    """A PoP where only two of the design's lines meet is below the threshold."""
    keys = {edge_key("mid", "b1"), edge_key("mid", "b2")}
    design = _design(("b1", "b2"), keys)
    pops = [pop(name) for name in ("mid", "b1", "b2")]
    assert convergence_promotion_ids(design, pops, _cities("mid")) == set()


def test_convergence_excludes_a_seated_backbone_node() -> None:
    """A node already in the backbone is never re-promoted, however many lines it carries."""
    keys = {edge_key("b1", n) for n in ("b2", "x", "y")}
    design = _design(("b1", "b2"), keys)
    pops = [pop(name) for name in ("b1", "b2", "x", "y")]
    assert convergence_promotion_ids(design, pops, _cities("b1", "b2", "x", "y")) == set()


def test_convergence_excludes_a_non_data_center_crossing() -> None:
    """A >= 3-line crossing with no data center stays transit -- the gate is absolute."""
    keys = {edge_key("hub", n) for n in ("b1", "b2", "x")}
    design = _design(("b1", "b2"), keys)
    pops = [pop(name) for name in ("hub", "b1", "b2", "x")]
    # hub is not in the data-center set, so it is not eligible for promotion.
    assert convergence_promotion_ids(design, pops, _cities("b1", "b2", "x")) == set()


# --- direct helper coverage ------------------------------------------------------------

def test_vertex_straightness_is_zero_without_reachable_vertices() -> None:
    """Vertex straightness is zero when no other PoP is reachable."""
    assert vertex_straightness("a", {"a": pop("a")}, {}) == 0.0


def test_vertex_straightness_skips_zero_length_hops() -> None:
    """Vertex straightness ignores hops between coincident PoPs."""
    by_id = {"a": pop("a", 0.0, 0.0), "b": pop("b", 0.0, 0.0)}
    assert vertex_straightness("a", by_id, {"b": "a"}) == 0.0


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
    return design_inputs_from_edges(
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
    plan = search_plan(["a", "b", "c", "d"], strength=strength)
    design = best_design_at_size(_mesh_inputs(), plan, 2)
    assert design is not None and set(design.backbone_ids) == {"a", "b"}


def test_best_design_at_size_returns_none_when_nothing_feasible() -> None:
    """With no feasible backbone set at a size, the search returns None for that size.

    The two candidate backbone PoPs sit in separate components, so neither can reach the
    other to wire its mesh links and no backbone set of that size is feasible.
    """
    edges = physical({("c1", "x"): 1.0, ("c2", "y"): 1.0})
    inputs = design_inputs_from_edges(["c1", "c2", "x", "y"], edges, {"c1", "c2"}, [access("s")])
    assert best_design_at_size(inputs, search_plan(["c1", "c2"]), 2) is None


def test_required_backbone_is_fixed_into_every_set() -> None:
    """Required backbone nodes appear in every candidate set the search considers."""
    forced = ForcedLinks(required_backbone=frozenset({"a"}))
    plan = search_plan(["a", "b", "c"], forced_links=forced)
    assert backbone_combinations(plan, 2) == [("a", "b"), ("a", "c")]


def test_backbone_combinations_empty_when_size_below_required() -> None:
    """No backbone set exists when more nodes are required than the size allows."""
    forced = ForcedLinks(required_backbone=frozenset({"a", "b"}))
    plan = search_plan(["a", "b"], forced_links=forced)
    assert backbone_combinations(plan, 1) == []


def test_backbone_combination_count_zero_when_size_below_required() -> None:
    """The count is zero when more nodes are required than the size allows."""
    forced = ForcedLinks(required_backbone=frozenset({"a", "b"}))
    plan = search_plan(["a", "b"], forced_links=forced)
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
    inputs = design_inputs_from_edges([], {}, set(), [])
    plan = search_plan([f"c{index}" for index in range(40)])
    with pytest.raises(ValueError):
        search_best_design(inputs, DesignParams(min_backbone_count=20), plan)


def test_search_raises_when_no_size_is_feasible() -> None:
    """The search raises when no backbone set of any size yields a feasible design.

    The two candidate backbone PoPs sit in separate components, so they can never reach
    each other to wire their mesh links and no size is feasible.
    """
    edges = physical({("c1", "x"): 1.0, ("c2", "y"): 1.0})
    inputs = design_inputs_from_edges(["c1", "c2", "x", "y"], edges, {"c1", "c2"}, [access("s")])
    plan = search_plan(["c1", "c2"])
    with pytest.raises(ValueError):
        search_best_design(inputs, DesignParams(min_backbone_count=2), plan)


def test_build_search_plan_ranks_candidates_by_strength() -> None:
    """Every eligible PoP is a backbone candidate, ranked by strength."""
    edges = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})
    inputs = design_inputs_from_edges(["a", "b", "c"], edges, {"a", "b", "c"})
    plan = build_search_plan(inputs, {"a", "b", "c"}, RoleOverrides(), DesignParams())
    assert set(plan.backbone_candidates) == {"a", "b", "c"}


def test_build_search_plan_fixes_promoted_nodes_into_required() -> None:
    """Convergence-promoted nodes join the operator-forced nodes in the required set."""
    edges = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})
    inputs = design_inputs_from_edges(["a", "b", "c"], edges, {"a", "b", "c"})
    overrides = RoleOverrides(forced_backbone_ids=frozenset({"a"}))
    plan = build_search_plan(
        inputs, {"a", "b", "c"}, overrides, DesignParams(), frozenset({"b"})
    )
    assert plan.required_backbone == frozenset({"a", "b"})


def _far_demand_inputs_plan(exempt: bool = False) -> tuple[DesignInputs, _SearchPlan]:
    """Two central nodes far (by geography) from west/east demand, plus two candidates.

    Shared by the growth and cap tests: a permissive coverage target holds the backbone
    at the two-node floor, while a tight one would grow it to seat a western (cw) and an
    eastern (ce) node that bring the far demand within reach. Every demand vertex wires
    into the graph through the central pair (cc1/cc2), so it always homes; the geography
    is what drives -- or holds -- the coverage growth. With ``exempt`` set, the demand
    vertices are marked exempt from the distance constraint.
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
    if exempt:
        access_nodes = [
            replace(node, exempt_from_distance_constraint=True) for node in access_nodes
        ]
    inputs = design_inputs_from_edges(ids, edges, {"cc1", "cc2", "cw", "ce"}, access_nodes, coords)
    plan = search_plan(
        ["cc1", "cc2", "cw", "ce"],
        strength={"cc1": 3.0, "cc2": 3.0, "cw": 1.0, "ce": 1.0},
    )
    return inputs, plan


def test_search_holds_at_the_floor_under_a_permissive_target() -> None:
    """A permissive coverage target leaves the backbone at the strength-chosen floor."""
    inputs, plan = _far_demand_inputs_plan()
    params = DesignParams(
        min_backbone_count=2, datacenter_cities=frozenset(),
        tuning=Tuning(backbone_coverage_target_miles=100_000),
    )
    assert search_best_design(inputs, params, plan).backbone_ids == ("cc1", "cc2")


def test_search_grows_past_the_floor_to_cover_far_demand() -> None:
    """Past the floor, nodes are added until far demand is within the coverage target."""
    inputs, plan = _far_demand_inputs_plan()
    params = DesignParams(
        min_backbone_count=2, datacenter_cities=frozenset(),
        tuning=Tuning(backbone_coverage_target_miles=300),
    )
    assert set(search_best_design(inputs, params, plan).backbone_ids) == {"cc1", "cc2", "cw", "ce"}


def test_exempt_demand_does_not_drive_coverage_growth() -> None:
    """Demand marked exempt from the distance constraint holds the backbone at its floor.

    Under the same 300 mi target that grows this design to four nodes when the far demand
    counts, marking that demand exempt drops it from the stop test, so growth never starts.
    """
    inputs, plan = _far_demand_inputs_plan(exempt=True)
    params = DesignParams(
        min_backbone_count=2, datacenter_cities=frozenset(),
        tuning=Tuning(backbone_coverage_target_miles=300),
    )
    assert search_best_design(inputs, params, plan).backbone_ids == ("cc1", "cc2")


def test_search_exhausts_its_candidates_under_an_unreachable_target() -> None:
    """An unreachable target adds every coverage candidate, then stops when none remain.

    The two extra nodes still leave demand outside an impossibly tight target, so growth
    runs out of candidates rather than meeting coverage or hitting a cap.
    """
    inputs, plan = _far_demand_inputs_plan()
    params = DesignParams(
        min_backbone_count=2, datacenter_cities=frozenset(),
        tuning=Tuning(backbone_coverage_target_miles=1),
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
        tuning=Tuning(backbone_coverage_target_miles=300),
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
    inputs = design_inputs_from_edges(
        ["c1", "c2", "p", "q"], edges, {"c1", "c2", "p"}, [access("s", 40.0, -80.5)], coords
    )
    plan = search_plan(["c1", "c2", "p"], strength={"c1": 3.0, "c2": 3.0, "p": 1.0})
    params = DesignParams(
        min_backbone_count=2, datacenter_cities=frozenset(),
        tuning=Tuning(backbone_coverage_target_miles=300),
    )
    assert search_best_design(inputs, params, plan).backbone_ids == ("c1", "c2")


def test_synthesize_rejects_forced_nodes_split_across_pockets() -> None:
    """Synthesis fails loudly when forced nodes straddle a single-fiber cut."""
    vertices = [pop(name) for name in TWO_POCKET_IDS]
    params = DesignParams(
        min_backbone_count=2,
        forced_backbone_names=("a", "d"),
        datacenter_cities=_cities(*TWO_POCKET_IDS),
    )
    pinned, edges, overrides = apply_role_overrides(vertices, TWO_POCKET_EDGES, params)
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


# --- backbone placement: the free-for-all gate (datacenter_cities is None) -------------

def test_eligible_includes_any_pop_when_gate_is_open() -> None:
    """With the gate open (datacenter_cities=None), every degree-two PoP is eligible."""
    edges = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("c", "a"): 1.0})
    pops = [pop(name) for name in ("a", "b", "c")]
    eligible = compute_eligible_backbone_ids(pops, build_adjacency(edges), None)
    assert eligible == {"a", "b", "c"}


def test_eligible_still_excludes_a_spur_when_gate_is_open() -> None:
    """The degree-one spur exclusion holds in free-for-all -- it can never path redundantly."""
    edges = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("c", "a"): 1.0, ("a", "spur"): 1.0})
    pops = [pop(name) for name in ("a", "b", "c", "spur")]
    eligible = compute_eligible_backbone_ids(pops, build_adjacency(edges), None)
    assert "spur" not in eligible


def test_convergence_promotes_any_hub_when_gate_is_open() -> None:
    """With the gate open, a >= 3-line crossing promotes even off every data-center city."""
    keys = {edge_key("hub", n) for n in ("b1", "b2", "x")}
    design = _design(("b1", "b2"), keys)
    pops = [pop(name) for name in ("hub", "b1", "b2", "x")]
    promoted = convergence_promotion_ids(design, pops, None)
    assert promoted == {"hub"}


def test_apply_role_overrides_accepts_any_pin_when_gate_is_open() -> None:
    """With the gate open, a forced pin at any city resolves rather than being rejected."""
    params = DesignParams(forced_backbone_names=("a",), datacenter_cities=None)
    _vertices, _edges, overrides = apply_role_overrides(
        [pop("a"), pop("b")], physical({("a", "b"): 1.0}), params
    )
    assert overrides.forced_backbone_ids == frozenset({"a"})


def test_synthesize_seats_a_backbone_off_every_data_center_city_when_gate_is_open() -> None:
    """An open gate lets synthesis build a backbone from PoPs at no data-center city.

    The same graph with the gate on raises (see
    ``test_not_enough_eligible_pops_is_rejected``); opening it seats a design.
    """
    design = synthesize_two_tier_design(
        fixtures.ring_vertices(),
        fixtures.ring_physical_edges(),
        DesignParams(min_backbone_count=2, datacenter_cities=None),
    )
    assert len(design.backbone_ids) >= 2


def test_open_gate_with_too_few_eligible_pops_is_rejected() -> None:
    """Even with the gate open, too few degree-two PoPs to home the backbone is rejected."""
    with pytest.raises(ValueError):
        synthesize_two_tier_design(
            [pop("a"), pop("b")], physical({("a", "b"): 1.0}),
            DesignParams(datacenter_cities=None),
        )
