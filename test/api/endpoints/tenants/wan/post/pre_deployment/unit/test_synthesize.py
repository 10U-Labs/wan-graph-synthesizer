from __future__ import annotations

from dataclasses import replace

import pytest

import fixtures
from fixtures import (
    TRIANGLE,
    TWO_POCKET_LINKS,
    TWO_POCKET_IDS,
    synthesis_inputs_from_links,
    search_plan,
)
from synthesizer.input_graph import link_key
from synthesizer.model import (
    Synthesis,
    SynthesisInputs,
    SynthesisMetrics,
    SynthesisParams,
    ForcedLinks,
    RoleExclusions,
    RoleOverrides,
    Tuning,
)
from synthesizer.survivable import FiberChoice, FiberInputs, choose_fiber
from synthesizer.synthesize import (
    backbone_combination_count,
    backbone_combinations,
    best_backbone_at_size,
    build_search_plan,
    convergence_promotion_ids,
    compute_eligible_backbone_ids,
    enumeration_limit,
    search_best_synthesis,
    synthesize_two_tier,
    total_memory_bytes,
)
from synthesizer.search_plan import _SearchPlan
from synthesizer.graphs import build_adjacency
from synthesizer.overrides import apply_role_overrides
from synthesizer.strength import site_straightness

pop = fixtures.carrier_pop
physical = fixtures.fiber_segments_from
access = fixtures.access_site
TRIANGLE_SITES = [pop("a"), pop("b"), pop("c"), access("s", 40.0, -99.0)]


def test_min_backbone_count_below_two_is_rejected() -> None:
    with pytest.raises(ValueError):
        synthesize_two_tier(
            TRIANGLE_SITES, TRIANGLE, SynthesisParams(min_backbone_count=1)
        )


def test_max_backbone_count_below_min_is_rejected() -> None:
    with pytest.raises(ValueError):
        synthesize_two_tier(
            TRIANGLE_SITES, TRIANGLE, SynthesisParams(min_backbone_count=3, max_backbone_count=2)
        )


def test_forced_backbone_exceeding_max_count_is_rejected() -> None:
    with pytest.raises(ValueError):
        synthesize_two_tier(
            TRIANGLE_SITES, TRIANGLE,
            SynthesisParams(min_backbone_count=2, max_backbone_count=2),
            RoleOverrides(forced_backbone_ids=frozenset({"a", "b", "c"})),
        )


def test_unknown_pop_ids_are_rejected() -> None:
    with pytest.raises(ValueError):
        synthesize_two_tier(
            [pop("a"), pop("b")], physical({("a", "c"): 1.0}), SynthesisParams()
        )


def test_pop_without_links_is_rejected() -> None:
    with pytest.raises(ValueError):
        synthesize_two_tier(
            [pop("a"), pop("b"), pop("c")], physical({("a", "b"): 1.0}), SynthesisParams()
        )


def test_not_enough_eligible_pops_is_rejected() -> None:
    with pytest.raises(ValueError):
        synthesize_two_tier(
            [pop("a"), pop("b")], physical({("a", "b"): 1.0}),
            SynthesisParams(),
        )


def test_synthesizes_ring_to_a_feasible_synthesis() -> None:
    synthesis = synthesize_two_tier(
        fixtures.ring_sites(), fixtures.ring_fiber_segments(), fixtures.ring_params()
    )
    assert len(synthesis.backbone_ids) >= 2


def test_min_backbone_count_is_the_floor_when_feasible() -> None:
    synthesis = synthesize_two_tier(
        fixtures.ring_sites(), fixtures.ring_fiber_segments(),
        SynthesisParams(min_backbone_count=3),
    )
    assert len(synthesis.backbone_ids) == 3


def test_backbone_grows_past_the_floor_to_seat_more_forced_nodes() -> None:
    synthesis = synthesize_two_tier(
        fixtures.ring_sites(), fixtures.ring_fiber_segments(),
        SynthesisParams(min_backbone_count=2),
        RoleOverrides(forced_backbone_ids=frozenset({"P1", "P3", "P5"})),
    )
    assert len(synthesis.backbone_ids) == 3


def test_no_feasible_synthesis_is_rejected() -> None:
    links = physical({("x1", "b1"): 1.0, ("b1", "y1"): 1.0, ("x2", "b2"): 1.0, ("b2", "y2"): 1.0})
    sites = [pop(name) for name in ("x1", "b1", "y1", "x2", "b2", "y2")]
    with pytest.raises(ValueError):
        synthesize_two_tier(
            sites, links,
            SynthesisParams(min_backbone_count=2),
        )


def test_honors_a_forced_backbone_override() -> None:
    synthesis = synthesize_two_tier(
        fixtures.ring_sites(), fixtures.ring_fiber_segments(),
        SynthesisParams(min_backbone_count=2),
        RoleOverrides(forced_backbone_ids=frozenset({"P3"})),
    )
    assert "P3" in synthesis.backbone_ids


def test_synthesize_promotes_a_convergence_hub() -> None:
    synthesis = fixtures.convergence_hub_artifacts().synthesis
    assert "hub_dc" in synthesis.backbone_ids


_UNPROMOTED_CONVERGENCE = fixtures.convergence_hub_artifacts(promote_convergences=False).synthesis


def test_promotion_disabled_leaves_a_convergence_hub_transit() -> None:
    assert "hub_dc" not in _UNPROMOTED_CONVERGENCE.backbone_ids


_CAPPED_CONVERGENCE = fixtures.convergence_hub_artifacts(max_backbone_count=4).synthesis


def test_backbone_cap_blocks_a_convergence_promotion() -> None:
    assert "hub_dc" not in _CAPPED_CONVERGENCE.backbone_ids


def test_capped_convergence_synthesis_fills_its_backbone_budget() -> None:
    assert len(_CAPPED_CONVERGENCE.backbone_ids) == 4


def test_eligible_excludes_a_degree_one_spur() -> None:
    links = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("c", "a"): 1.0, ("a", "spur"): 1.0})
    pops = [pop(name) for name in ("a", "b", "c", "spur")]
    eligible = compute_eligible_backbone_ids(
        pops, build_adjacency(links)
    )
    assert "spur" not in eligible


def test_eligible_includes_a_degree_two_pop() -> None:
    links = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("c", "a"): 1.0})
    pops = [pop(name) for name in ("a", "b", "c")]
    eligible = compute_eligible_backbone_ids(pops, build_adjacency(links))
    assert eligible == {"a", "b", "c"}


def _synthesis(
    backbone_ids: tuple[str, ...],
    fiber_segment_keys: set[tuple[str, str]],
) -> Synthesis:
    return Synthesis(
        backbone_ids=backbone_ids,
        transit_ids=(),
        access_paths=[],
        fiber_segment_keys=fiber_segment_keys,
        path_uses=[],
        metrics=SynthesisMetrics(0.0, 0.0, 0.0),
    )


def test_convergence_promotes_a_transit_hub() -> None:
    keys = {link_key("hub", n) for n in ("b1", "b2", "x", "y")}
    synthesis = _synthesis(("b1", "b2"), keys)
    assert convergence_promotion_ids(synthesis) == {"hub"}


def test_convergence_skips_a_two_line_crossing() -> None:
    keys = {link_key("mid", "b1"), link_key("mid", "b2")}
    synthesis = _synthesis(("b1", "b2"), keys)
    assert convergence_promotion_ids(synthesis) == set()


def test_convergence_excludes_a_seated_backbone_node() -> None:
    keys = {link_key("b1", n) for n in ("b2", "x", "y")}
    synthesis = _synthesis(("b1", "b2"), keys)
    assert convergence_promotion_ids(synthesis) == set()


def test_site_straightness_is_zero_without_reachable_sites() -> None:
    assert site_straightness("a", {"a": pop("a")}, {}) == 0.0


def test_site_straightness_skips_zero_length_hops() -> None:
    by_id = {"a": pop("a", 0.0, 0.0), "b": pop("b", 0.0, 0.0)}
    assert site_straightness("a", by_id, {"b": "a"}) == 0.0


MESH_LINKS = physical(
    {
        ("a", "b"): 1.0, ("a", "c"): 1.0, ("a", "d"): 1.0,
        ("b", "c"): 1.0, ("b", "d"): 1.0, ("c", "d"): 1.0,
        ("s", "a"): 1.0, ("s", "b"): 1.0, ("s", "c"): 1.0, ("s", "d"): 1.0,
    }
)
MESH_COORDS = {"a": (0.0, 1.0), "b": (0.0, 2.0), "c": (0.0, 50.0), "d": (0.0, 51.0)}


def _mesh_inputs() -> SynthesisInputs:
    return synthesis_inputs_from_links(
        ["a", "b", "c", "d"], MESH_LINKS, {"a", "b", "c", "d"},
        [access("s", 0.0, 0.0)], MESH_COORDS,
    )


@pytest.mark.parametrize(
    "strength",
    [
        {"a": 10.0, "b": 10.0, "c": 1.0, "d": 1.0},
        {"a": 10.0, "b": 10.0, "c": 10.0, "d": 10.0},
    ],
)
def test_best_backbone_at_size_selects_strongest_then_least_last_mile(
    strength: dict[str, float],
) -> None:
    plan = search_plan(["a", "b", "c", "d"], strength=strength)
    seats = best_backbone_at_size(_mesh_inputs(), plan, 2)
    assert seats is not None and set(seats) == {"a", "b"}


def test_best_backbone_at_size_returns_none_when_nothing_feasible() -> None:
    links = physical({("c1", "x"): 1.0, ("c2", "y"): 1.0})
    inputs = synthesis_inputs_from_links(["c1", "c2", "x", "y"], links, {"c1", "c2"}, [access("s")])
    assert best_backbone_at_size(inputs, search_plan(["c1", "c2"]), 2) is None


def test_required_backbone_is_fixed_into_every_set() -> None:
    forced = ForcedLinks(required_backbone=frozenset({"a"}))
    plan = search_plan(["a", "b", "c"], forced_links=forced)
    assert backbone_combinations(plan, 2) == [("a", "b"), ("a", "c")]


def test_backbone_combinations_empty_when_size_below_required() -> None:
    forced = ForcedLinks(required_backbone=frozenset({"a", "b"}))
    plan = search_plan(["a", "b"], forced_links=forced)
    assert backbone_combinations(plan, 1) == []


def test_backbone_combination_count_zero_when_size_below_required() -> None:
    forced = ForcedLinks(required_backbone=frozenset({"a", "b"}))
    plan = search_plan(["a", "b"], forced_links=forced)
    assert backbone_combination_count(plan, 1) == 0


def test_enumeration_limit_grows_with_available_memory() -> None:
    params = SynthesisParams()
    assert enumeration_limit(32 * 10**9, params) > enumeration_limit(16 * 10**9, params)


def test_total_memory_honors_the_lambda_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_MEMORY_SIZE", "8192")
    assert total_memory_bytes() == 8192 * 1024 * 1024


def test_total_memory_falls_back_to_physical_ram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_MEMORY_SIZE", raising=False)
    assert total_memory_bytes() > 0


def test_search_refuses_a_space_too_large_for_memory() -> None:
    inputs = synthesis_inputs_from_links([], {}, set(), [])
    plan = search_plan([f"c{index}" for index in range(40)])
    with pytest.raises(ValueError):
        search_best_synthesis(inputs, SynthesisParams(min_backbone_count=20), plan)


def test_search_raises_when_no_size_is_feasible() -> None:
    links = physical({("c1", "x"): 1.0, ("c2", "y"): 1.0})
    inputs = synthesis_inputs_from_links(["c1", "c2", "x", "y"], links, {"c1", "c2"}, [access("s")])
    plan = search_plan(["c1", "c2"])
    with pytest.raises(ValueError):
        search_best_synthesis(inputs, SynthesisParams(min_backbone_count=2), plan)


def test_build_search_plan_ranks_candidates_by_strength() -> None:
    links = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})
    inputs = synthesis_inputs_from_links(["a", "b", "c"], links, {"a", "b", "c"})
    plan = build_search_plan(inputs, {"a", "b", "c"}, RoleOverrides(), SynthesisParams())
    assert set(plan.backbone_candidates) == {"a", "b", "c"}


def test_build_search_plan_fixes_promoted_nodes_into_required() -> None:
    links = physical({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})
    inputs = synthesis_inputs_from_links(["a", "b", "c"], links, {"a", "b", "c"})
    overrides = RoleOverrides(forced_backbone_ids=frozenset({"a"}))
    plan = build_search_plan(
        inputs, {"a", "b", "c"}, overrides, SynthesisParams(), frozenset({"b"})
    )
    assert plan.required_backbone == frozenset({"a", "b"})


def _far_demand_inputs_plan(exempt: bool = False) -> tuple[SynthesisInputs, _SearchPlan]:
    links = physical(
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
    inputs = synthesis_inputs_from_links(
        ids, links, {"cc1", "cc2", "cw", "ce"}, access_nodes, coords
    )
    plan = search_plan(
        ["cc1", "cc2", "cw", "ce"],
        strength={"cc1": 3.0, "cc2": 3.0, "cw": 1.0, "ce": 1.0},
    )
    return inputs, plan


def _fiber_choices(monkeypatch: pytest.MonkeyPatch, target_miles: int) -> int:
    inputs, plan = _far_demand_inputs_plan()
    params = SynthesisParams(
        min_backbone_count=2,
        tuning=Tuning(backbone_coverage_target_miles=target_miles),
    )
    counted: list[tuple[str, ...]] = []

    def counting(fiber_inputs: FiberInputs) -> FiberChoice:
        counted.append(fiber_inputs.backbone_ids)
        return choose_fiber(fiber_inputs)

    monkeypatch.setattr("synthesizer.backbone.choose_fiber", counting)
    search_best_synthesis(inputs, params, plan)
    return len(counted)


def test_a_search_that_grows_past_the_floor_still_chooses_its_fiber_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _fiber_choices(monkeypatch, 300) == 1


def test_a_search_that_seats_nothing_past_the_floor_chooses_its_fiber_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _fiber_choices(monkeypatch, 100_000) == 1


def test_search_holds_at_the_floor_under_a_permissive_target() -> None:
    inputs, plan = _far_demand_inputs_plan()
    params = SynthesisParams(
        min_backbone_count=2,
        tuning=Tuning(backbone_coverage_target_miles=100_000),
    )
    assert search_best_synthesis(inputs, params, plan).backbone_ids == ("cc1", "cc2")


def test_search_grows_past_the_floor_to_cover_far_demand() -> None:
    inputs, plan = _far_demand_inputs_plan()
    params = SynthesisParams(
        min_backbone_count=2,
        tuning=Tuning(backbone_coverage_target_miles=300),
    )
    seated = set(search_best_synthesis(inputs, params, plan).backbone_ids)
    assert seated == {"cc1", "cc2", "cw", "ce"}


def test_exempt_demand_does_not_drive_coverage_growth() -> None:
    inputs, plan = _far_demand_inputs_plan(exempt=True)
    params = SynthesisParams(
        min_backbone_count=2,
        tuning=Tuning(backbone_coverage_target_miles=300),
    )
    assert search_best_synthesis(inputs, params, plan).backbone_ids == ("cc1", "cc2")


def test_search_exhausts_its_candidates_under_an_unreachable_target() -> None:
    inputs, plan = _far_demand_inputs_plan()
    params = SynthesisParams(
        min_backbone_count=2,
        tuning=Tuning(backbone_coverage_target_miles=1),
    )
    seated = set(search_best_synthesis(inputs, params, plan).backbone_ids)
    assert seated == {"cc1", "cc2", "cw", "ce"}


def test_max_backbone_count_caps_coverage_growth() -> None:
    inputs, plan = _far_demand_inputs_plan()
    params = SynthesisParams(
        min_backbone_count=2, max_backbone_count=3,
        tuning=Tuning(backbone_coverage_target_miles=300),
    )
    assert len(search_best_synthesis(inputs, params, plan).backbone_ids) == 3


def test_search_holds_at_the_floor_when_the_only_candidate_is_infeasible() -> None:
    links = physical(
        {
            ("c1", "c2"): 1.0, ("s", "c1"): 1.0, ("s", "c2"): 1.0, ("p", "q"): 1.0,
        }
    )
    coords = {
        "c1": (40.0, -100.0), "c2": (40.0, -99.0), "p": (40.0, -81.0),
    }
    inputs = synthesis_inputs_from_links(
        ["c1", "c2", "p", "q"], links, {"c1", "c2", "p"}, [access("s", 40.0, -80.5)], coords
    )
    plan = search_plan(["c1", "c2", "p"], strength={"c1": 3.0, "c2": 3.0, "p": 1.0})
    params = SynthesisParams(
        min_backbone_count=2,
        tuning=Tuning(backbone_coverage_target_miles=300),
    )
    assert search_best_synthesis(inputs, params, plan).backbone_ids == ("c1", "c2")


def test_synthesize_rejects_forced_nodes_split_across_pockets() -> None:
    sites = [pop(name) for name in TWO_POCKET_IDS]
    params = SynthesisParams(
        min_backbone_count=2,
        forced_backbone_names=("a", "d"),
    )
    pinned, links, overrides = apply_role_overrides(sites, TWO_POCKET_LINKS, params)
    with pytest.raises(ValueError):
        synthesize_two_tier(pinned, links, params, overrides)


def test_apply_role_overrides_resolves_a_forced_backbone_pin() -> None:
    params = SynthesisParams(forced_backbone_names=("a",))
    _sites, _links, overrides = apply_role_overrides(
        [pop("a"), pop("b")], physical({("a", "b"): 1.0}), params
    )
    assert overrides.forced_backbone_ids == frozenset({"a"})


def test_apply_role_overrides_rejects_a_forced_and_prohibited_pop() -> None:
    params = SynthesisParams(
        forced_backbone_names=("a",),
        exclusions=RoleExclusions(prohibited_backbone_names=("a",)),
    )
    with pytest.raises(ValueError):
        apply_role_overrides([pop("a"), pop("b")], physical({("a", "b"): 1.0}), params)
