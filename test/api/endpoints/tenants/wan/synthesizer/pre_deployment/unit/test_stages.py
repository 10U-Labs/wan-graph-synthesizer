"""Unit tests for the WAN design pipeline steps."""

from __future__ import annotations

import fixtures
from synthesizer.stages import dual_home, finalize
from synthesizer.model import DesignParams


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
