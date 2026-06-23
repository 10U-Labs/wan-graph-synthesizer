"""Unit tests for the WAN design pipeline steps."""

from __future__ import annotations

from pathlib import Path

import fixtures
from seed import load_off_net_sites
from wan_synthesizer.stages import dual_home, finalize
from wan_synthesizer.model import DesignParams, DesignPaths


def test_dual_home_returns_a_graph_without_off_net(tmp_path: Path) -> None:
    """dual_home attaches demand when no off-net file is configured."""
    vertex_files, edges = fixtures.write_solvable_inputs(tmp_path)
    vertices, physical_edges = fixtures.load_design_inputs(
        DesignPaths(vertex_files, edges)
    )
    homed_vertices, homed_edges = dual_home(
        vertices, physical_edges, fixtures.ring_params(), []
    )
    assert homed_vertices and homed_edges


def test_dual_home_realizes_a_forced_off_net_site(tmp_path: Path) -> None:
    """dual_home synthesizes a local-fiber twin for a forced off-net seat."""
    paths, name = fixtures.write_off_net_solvable_inputs(tmp_path)
    params = DesignParams(min_core_count=2, forced_core_names=(name,))
    vertices, physical_edges = fixtures.load_design_inputs(paths)
    sites = load_off_net_sites(paths.off_net_path) if paths.off_net_path else []
    homed_vertices, _edges = dual_home(vertices, physical_edges, params, sites)
    assert any(vertex.id.startswith("offnet_") for vertex in homed_vertices)


def test_finalize_validates_a_design() -> None:
    """finalize validates a design and reports it connected."""
    art = fixtures.ring_artifacts()
    _vertices, _edges, _design, validation = finalize(
        art.vertices, art.physical_edges, art.design, fixtures.ring_params()
    )
    assert validation["connected"] is True
