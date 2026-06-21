"""Unit tests for the WAN design pipeline steps."""

from __future__ import annotations

from pathlib import Path

import pytest

import fixtures
from wan_designer.model import DesignParams, DesignPaths, is_carrier_pop
from wan_designer.offnet import load_off_net_sites
from wan_designer.stages import combine_substrate, dual_home, finalize, load_inputs


def test_load_inputs_loads_vertices_and_edges(tmp_path: Path) -> None:
    """load_inputs reads the configured vertices and carrier fiber edges."""
    vertex_files, edges = fixtures.write_solvable_inputs(tmp_path)
    vertices, physical_edges = load_inputs(DesignPaths(vertex_files, edges))
    assert vertices and physical_edges


def test_load_inputs_rejects_empty_vertices() -> None:
    """load_inputs rejects a config that yields no vertices."""
    with pytest.raises(ValueError):
        load_inputs(DesignPaths((), Path("unused.csv")))


def test_combine_substrate_keeps_only_carrier_pops(tmp_path: Path) -> None:
    """combine_substrate drops non-carrier vertices, keeping the carrier mesh."""
    vertex_files, edges = fixtures.write_solvable_inputs(tmp_path)
    carrier_pops, _edges = combine_substrate(DesignPaths(vertex_files, edges))
    assert carrier_pops and all(is_carrier_pop(vertex) for vertex in carrier_pops)


def test_dual_home_returns_a_graph_without_off_net(tmp_path: Path) -> None:
    """dual_home attaches demand when no off-net file is configured."""
    vertex_files, edges = fixtures.write_solvable_inputs(tmp_path)
    vertices, physical_edges = load_inputs(DesignPaths(vertex_files, edges))
    homed_vertices, homed_edges = dual_home(
        vertices, physical_edges, fixtures.ring_params(), []
    )
    assert homed_vertices and homed_edges


def test_dual_home_realizes_a_forced_off_net_site(tmp_path: Path) -> None:
    """dual_home synthesizes a local-fiber twin for a forced off-net seat."""
    paths, name = fixtures.write_off_net_solvable_inputs(tmp_path)
    params = DesignParams(min_core_count=2, forced_core_names=(name,))
    vertices, physical_edges = load_inputs(paths)
    sites = load_off_net_sites(paths.off_net_path) if paths.off_net_path else []
    homed_vertices, _edges = dual_home(vertices, physical_edges, params, sites)
    assert any(vertex.id.startswith("offnet_") for vertex in homed_vertices)


def test_finalize_validates_without_augmentation() -> None:
    """finalize validates a design and reports it connected."""
    art = fixtures.ring_artifacts()
    _vertices, _edges, _design, validation = finalize(
        art.vertices, art.physical_edges, art.design, fixtures.ring_params(), False
    )
    assert validation["connected"] is True


def test_finalize_validates_with_augmentation() -> None:
    """finalize augments physical resilience and still validates connected."""
    art = fixtures.ring_artifacts()
    _vertices, _edges, _design, validation = finalize(
        art.vertices, art.physical_edges, art.design, fixtures.ring_params(), True
    )
    assert validation["connected"] is True
