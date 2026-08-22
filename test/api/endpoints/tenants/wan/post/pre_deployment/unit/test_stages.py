from __future__ import annotations

import fixtures
import pytest
from synthesizer.stages import dual_home, finalize
from synthesizer.model import SynthesisParams, Tuning, ValidationReport

_TWO_DIVERSE_PATHS = Tuning(backbone_number_of_diverse_paths=2)


def test_dual_home_returns_a_graph_without_off_net() -> None:
    homed_sites, homed_paths = dual_home(
        fixtures.ring_sites(), fixtures.ring_fiber_segments(), fixtures.ring_params(), []
    )
    assert homed_sites and homed_paths


def test_dual_home_realizes_a_forced_off_net_site() -> None:
    site, params = fixtures.forced_off_net_case()
    homed_sites, _links = dual_home(
        fixtures.ring_sites(), fixtures.ring_fiber_segments(), params, [site]
    )
    assert any(site.id.startswith("offnet_") for site in homed_sites)


def test_dual_home_fabricates_a_forced_on_net_location() -> None:
    luke = fixtures.access_site("Luke", 40.5, -100.0)
    params = SynthesisParams(
        min_backbone_count=2,
        forced_backbone_names=("Luke",),
    )
    homed_sites, _links = dual_home(
        [*fixtures.ring_sites(), luke], fixtures.ring_fiber_segments(), params, []
    )
    assert any(site.id.startswith("fac_") for site in homed_sites)


def test_finalize_validates_a_synthesis() -> None:
    art = fixtures.ring_artifacts()
    _sites, _links, _synthesis, validation = finalize(
        art.sites, art.fiber_segments, art.synthesis, fixtures.ring_params()
    )
    assert validation["connected"] is True


def test_finalize_returns_the_synthesis_unchanged() -> None:
    art = fixtures.ring_artifacts()
    _sites, _links, synthesis, _validation = finalize(
        art.sites, art.fiber_segments, art.synthesis, fixtures.ring_params()
    )
    assert synthesis is art.synthesis


def test_finalize_reports_the_independent_mesh_target() -> None:
    art = fixtures.ring_artifacts()
    _sites, _links, _synthesis, validation = finalize(
        art.sites, art.fiber_segments, art.synthesis, fixtures.ring_params()
    )
    assert validation["backbone_meets_independent_mesh_link_target"] is True


def test_finalize_refuses_a_synthesis_short_of_the_configured_number_of_diverse_paths() -> None:
    synthesis = fixtures.meshed_backbone_synthesis(
        fixtures.SHARED_TRANSIT_PATHS, fixtures.SHARED_TRANSIT_BACKBONE
    )
    params = SynthesisParams(min_backbone_count=2, tuning=_TWO_DIVERSE_PATHS)
    with pytest.raises(ValueError, match="independently failing backbone mesh links at"):
        finalize(list(fixtures.carrier_pops_by_id("abcx").values()), {}, synthesis, params)


def test_finalize_holds_a_node_to_the_ceiling_of_the_merged_carriers_it_is_given() -> None:
    synthesis = fixtures.meshed_backbone_synthesis(
        fixtures.SHARED_TRANSIT_PATHS, fixtures.SHARED_TRANSIT_BACKBONE
    )
    params = SynthesisParams(min_backbone_count=2, tuning=_TWO_DIVERSE_PATHS)
    links = fixtures.fiber_segments_from({
        ("a", "x"): 1.0, ("x", "b"): 1.0, ("x", "c"): 1.0, ("b", "c"): 1.0,
    })
    _sites, _links, _synthesis, validation = finalize(
        list(fixtures.carrier_pops_by_id("abcx").values()), links, synthesis, params
    )
    assert validation["backbone_meets_independent_mesh_link_target"] is True


def _finalize_shared_transit(degree_exempt: frozenset[str]) -> ValidationReport:
    synthesis = fixtures.meshed_backbone_synthesis(
        fixtures.SHARED_TRANSIT_PATHS, fixtures.SHARED_TRANSIT_BACKBONE
    )
    params = SynthesisParams(min_backbone_count=2, tuning=_TWO_DIVERSE_PATHS)
    _sites, _links, _synthesis, validation = finalize(
        list(fixtures.carrier_pops_by_id("abcx").values()), {}, synthesis, params, degree_exempt
    )
    return validation


def test_finalize_accepts_a_synthesis_whose_only_shortfall_is_exempt() -> None:
    assert _finalize_shared_transit(frozenset({"a"}))[
        "backbone_meets_independent_mesh_link_target"
    ] is True


def test_finalize_reports_the_exempt_node_it_accepted() -> None:
    assert _finalize_shared_transit(frozenset({"a"}))["backbone_degree_exempt"] == [
        {"id": "a", "name": "a"}
    ]


def _finalize_split_backbone() -> None:
    finalize(
        list(fixtures.carrier_pops_by_id(fixtures.SPLIT_BACKBONE_CITIES).values()),
        fixtures.fiber_segments_from(fixtures.SPLIT_BACKBONE_SEGMENTS),
        fixtures.split_backbone_synthesis(),
        SynthesisParams(min_backbone_count=2),
    )


def test_finalize_refuses_a_synthesis_whose_sites_fall_into_more_than_one_group() -> None:
    with pytest.raises(ValueError, match="no fiber joins"):
        _finalize_split_backbone()


def test_the_refusal_says_how_many_groups_the_synthesis_fell_into() -> None:
    with pytest.raises(ValueError, match="falls into 2 groups"):
        _finalize_split_backbone()
