"""Unit tests for the WAN design pipeline steps."""

from __future__ import annotations

import fixtures
import pytest
from synthesizer.stages import dual_home, finalize
from synthesizer.model import DesignParams, Tuning, ValidationReport


def test_dual_home_returns_a_graph_without_off_net() -> None:
    """dual_home attaches demand when no off-net site is configured."""
    homed_vertices, homed_edges = dual_home(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(), fixtures.ring_params(), []
    )
    assert homed_vertices and homed_edges


def test_dual_home_realizes_a_forced_off_net_site() -> None:
    """dual_home synthesizes a local-fiber twin for a forced off-net seat."""
    site, params = fixtures.forced_off_net_case()
    homed_vertices, _edges = dual_home(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(), params, [site]
    )
    assert any(vertex.id.startswith("offnet_") for vertex in homed_vertices)


def test_dual_home_fabricates_a_forced_on_net_location() -> None:
    """dual_home fabricates an on-net twin for a forced demand location in our data."""
    # "Luke" is a demand vertex in the input; forcing it fabricates its on-net twin.
    luke = fixtures.access_vertex("Luke", 40.5, -100.0)
    params = DesignParams(
        min_backbone_count=2,
        forced_backbone_names=("Luke",),
        datacenter_cities=fixtures.ring_datacenter_cities()
        | {(luke.info.municipality, luke.info.state)},
    )
    homed_vertices, _edges = dual_home(
        [*fixtures.ring_vertices(), luke], fixtures.ring_physical_edges(), params, []
    )
    assert any(vertex.id.startswith("fac_") for vertex in homed_vertices)


def test_dual_home_fabricates_a_non_data_center_forced_location_when_gate_is_open() -> None:
    """With the gate open (datacenter_cities=None), dual_home fabricates a forced location."""
    luke = fixtures.access_vertex("Luke", 40.5, -100.0)
    params = DesignParams(
        min_backbone_count=2,
        forced_backbone_names=("Luke",),
        datacenter_cities=None,
    )
    homed_vertices, _edges = dual_home(
        [*fixtures.ring_vertices(), luke], fixtures.ring_physical_edges(), params, []
    )
    assert any(vertex.id.startswith("fac_") for vertex in homed_vertices)


def test_finalize_validates_a_design() -> None:
    """finalize validates a design and reports it connected."""
    art = fixtures.ring_artifacts()
    _vertices, _edges, _design, validation = finalize(
        art.vertices, art.physical_edges, art.design, fixtures.ring_params()
    )
    assert validation["connected"] is True


def test_finalize_returns_the_design_unchanged() -> None:
    """finalize passes the design through untouched alongside its validation report."""
    art = fixtures.ring_artifacts()
    _vertices, _edges, design, _validation = finalize(
        art.vertices, art.physical_edges, art.design, fixtures.ring_params()
    )
    assert design is art.design


def test_finalize_reports_the_independent_mesh_target() -> None:
    """finalize reports whether the mesh links of every backbone node fail independently."""
    art = fixtures.ring_artifacts()
    _vertices, _edges, _design, validation = finalize(
        art.vertices, art.physical_edges, art.design, fixtures.ring_params()
    )
    assert validation["backbone_meets_independent_mesh_link_target"] is True


def test_finalize_refuses_a_design_short_of_the_configured_number_of_diverse_paths() -> None:
    """A backbone node without the configured independent links makes finalize raise.

    Node a's two links both leave through transit city x, so one city's loss takes both
    and a holds a single independent link where the configuration asks for two.
    """
    design = fixtures.meshed_backbone_design(
        fixtures.SHARED_TRANSIT_PATHS, fixtures.SHARED_TRANSIT_BACKBONE
    )
    params = DesignParams(min_backbone_count=2, tuning=Tuning(backbone_number_of_diverse_paths=2))
    with pytest.raises(ValueError, match="independently failing backbone mesh links at"):
        finalize(list(fixtures.carrier_pops_by_id("abcx").values()), {}, design, params)


def test_finalize_holds_a_node_to_the_ceiling_of_the_substrate_it_is_given() -> None:
    """The same shortfall is no refusal once the fiber shows one link is all a can hold.

    Node a reaches b and c only through the transit city x, so its ceiling on this
    substrate is one -- and one is what it holds. finalize builds the ceilings from the
    fiber it is handed, so the design it refuses on a bare substrate finalizes on the real
    one.
    """
    design = fixtures.meshed_backbone_design(
        fixtures.SHARED_TRANSIT_PATHS, fixtures.SHARED_TRANSIT_BACKBONE
    )
    params = DesignParams(min_backbone_count=2, tuning=Tuning(backbone_number_of_diverse_paths=2))
    edges = fixtures.physical_edges_from({
        ("a", "x"): 1.0, ("x", "b"): 1.0, ("x", "c"): 1.0, ("b", "c"): 1.0,
    })
    _vertices, _edges, _design, validation = finalize(
        list(fixtures.carrier_pops_by_id("abcx").values()), edges, design, params
    )
    assert validation["backbone_meets_independent_mesh_link_target"] is True


def _finalize_shared_transit(degree_exempt: frozenset[str]) -> ValidationReport:
    """Finalize the shared-transit mesh, whose node a holds one independent link."""
    design = fixtures.meshed_backbone_design(
        fixtures.SHARED_TRANSIT_PATHS, fixtures.SHARED_TRANSIT_BACKBONE
    )
    params = DesignParams(min_backbone_count=2, tuning=Tuning(backbone_number_of_diverse_paths=2))
    _vertices, _edges, _design, validation = finalize(
        list(fixtures.carrier_pops_by_id("abcx").values()), {}, design, params, degree_exempt
    )
    return validation


def test_finalize_accepts_a_design_whose_only_shortfall_is_exempt() -> None:
    """Exempting the spur lets the same design finalize instead of being refused."""
    assert _finalize_shared_transit(frozenset({"a"}))[
        "backbone_meets_independent_mesh_link_target"
    ] is True


def test_finalize_reports_the_exempt_node_it_accepted() -> None:
    """The report finalize returns names the node whose shortfall was allowed."""
    assert _finalize_shared_transit(frozenset({"a"}))["backbone_degree_exempt"] == [
        {"id": "a", "name": "a"}
    ]
