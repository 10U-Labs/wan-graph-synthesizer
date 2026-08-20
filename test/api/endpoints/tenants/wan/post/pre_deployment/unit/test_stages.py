"""Unit tests for the WAN synthesis pipeline steps."""

from __future__ import annotations

import fixtures
import pytest
from synthesizer.stages import dual_home, finalize
from synthesizer.model import SynthesisParams, Tuning, ValidationReport

# What the shared-transit cases ask of every backbone node: two ways out that no single
# city's loss takes both of. The mesh they are run against gives node a only one, which is
# the shortfall those cases are about.
_TWO_DIVERSE_PATHS = Tuning(backbone_number_of_diverse_paths=2)


def test_dual_home_returns_a_graph_without_off_net() -> None:
    """dual_home attaches demand when no off-net site is configured."""
    homed_sites, homed_paths = dual_home(
        fixtures.ring_sites(), fixtures.ring_fiber_segments(), fixtures.ring_params(), []
    )
    assert homed_sites and homed_paths


def test_dual_home_realizes_a_forced_off_net_site() -> None:
    """dual_home synthesizes a local-fiber twin for a forced off-net seat."""
    site, params = fixtures.forced_off_net_case()
    homed_sites, _links = dual_home(
        fixtures.ring_sites(), fixtures.ring_fiber_segments(), params, [site]
    )
    assert any(site.id.startswith("offnet_") for site in homed_sites)


def test_dual_home_fabricates_a_forced_on_net_location() -> None:
    """dual_home fabricates an on-net twin for a forced demand location in our data."""
    # "Luke" is a demand site in the input; forcing it fabricates its on-net twin.
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
    """finalize validates a synthesis and reports it connected."""
    art = fixtures.ring_artifacts()
    _sites, _links, _synthesis, validation = finalize(
        art.sites, art.fiber_segments, art.synthesis, fixtures.ring_params()
    )
    assert validation["connected"] is True


def test_finalize_returns_the_synthesis_unchanged() -> None:
    """finalize passes the synthesis through untouched alongside its validation report."""
    art = fixtures.ring_artifacts()
    _sites, _links, synthesis, _validation = finalize(
        art.sites, art.fiber_segments, art.synthesis, fixtures.ring_params()
    )
    assert synthesis is art.synthesis


def test_finalize_reports_the_independent_mesh_target() -> None:
    """finalize reports whether the mesh links of every backbone node fail independently."""
    art = fixtures.ring_artifacts()
    _sites, _links, _synthesis, validation = finalize(
        art.sites, art.fiber_segments, art.synthesis, fixtures.ring_params()
    )
    assert validation["backbone_meets_independent_mesh_link_target"] is True


def test_finalize_refuses_a_synthesis_short_of_the_configured_number_of_diverse_paths() -> None:
    """A backbone node without the configured independent links makes finalize raise.

    Node a's two links both leave through transit city x, so one city's loss takes both
    and a holds a single independent link where the configuration asks for two.
    """
    synthesis = fixtures.meshed_backbone_synthesis(
        fixtures.SHARED_TRANSIT_PATHS, fixtures.SHARED_TRANSIT_BACKBONE
    )
    params = SynthesisParams(min_backbone_count=2, tuning=_TWO_DIVERSE_PATHS)
    with pytest.raises(ValueError, match="independently failing backbone mesh links at"):
        finalize(list(fixtures.carrier_pops_by_id("abcx").values()), {}, synthesis, params)


def test_finalize_holds_a_node_to_the_ceiling_of_the_merged_carriers_it_is_given() -> None:
    """The same shortfall is no refusal once the fiber shows one link is all a can hold.

    Node a reaches b and c only through the transit city x, so its ceiling on this
    fiber is one -- and one is what it holds. finalize builds the ceilings from the
    fiber it is handed, so the synthesis it refuses on bare fiber finalizes on the real
    one.
    """
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
    """Finalize the shared-transit mesh, whose node a holds one independent link."""
    synthesis = fixtures.meshed_backbone_synthesis(
        fixtures.SHARED_TRANSIT_PATHS, fixtures.SHARED_TRANSIT_BACKBONE
    )
    params = SynthesisParams(min_backbone_count=2, tuning=_TWO_DIVERSE_PATHS)
    _sites, _links, _synthesis, validation = finalize(
        list(fixtures.carrier_pops_by_id("abcx").values()), {}, synthesis, params, degree_exempt
    )
    return validation


def test_finalize_accepts_a_synthesis_whose_only_shortfall_is_exempt() -> None:
    """Exempting the spur lets the same synthesis finalize instead of being refused."""
    assert _finalize_shared_transit(frozenset({"a"}))[
        "backbone_meets_independent_mesh_link_target"
    ] is True


def test_finalize_reports_the_exempt_node_it_accepted() -> None:
    """The report finalize returns names the node whose shortfall was allowed."""
    assert _finalize_shared_transit(frozenset({"a"}))["backbone_degree_exempt"] == [
        {"id": "a", "name": "a"}
    ]


def _finalize_split_backbone() -> None:
    """Finalize a backbone in two groups: a reaches b through t, c reaches d, and no more.

    Each of the four seated sites holds the one link its own fiber can carry, so every site
    meets the count it is asked for and the diverse path check has nothing to say. Only the
    connectivity gate sees that the synthesis is two networks rather than one.
    """
    finalize(
        list(fixtures.carrier_pops_by_id(fixtures.SPLIT_BACKBONE_CITIES).values()),
        fixtures.fiber_segments_from(fixtures.SPLIT_BACKBONE_SEGMENTS),
        fixtures.split_backbone_synthesis(),
        SynthesisParams(min_backbone_count=2),
    )


def test_finalize_refuses_a_synthesis_whose_sites_fall_into_more_than_one_group() -> None:
    """A synthesis an operator could carry no traffic across is refused rather than returned.

    Publishing it hands the operator two networks described as one, and nothing downstream
    says so: the status reads success and every other finding in the report passes.
    """
    with pytest.raises(ValueError, match="no fiber joins"):
        _finalize_split_backbone()


def test_the_refusal_says_how_many_groups_the_synthesis_fell_into() -> None:
    """The message names the count, since a refusal nobody can act on is half a gate."""
    with pytest.raises(ValueError, match="falls into 2 groups"):
        _finalize_split_backbone()
