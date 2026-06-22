"""Unit tests for the three-tier design pipeline runner."""

from __future__ import annotations

from pathlib import Path

import pytest

import fixtures
from wan_designer.model import DesignParams, DesignPaths
from fixtures import run_design


def test_run_design_is_connected(tmp_path: Path) -> None:
    """Run design over a solvable graph validates as connected."""
    vertex_files, edges = fixtures.write_solvable_inputs(tmp_path)
    paths = DesignPaths(vertex_files, edges)
    artifacts = run_design(paths, fixtures.ring_params())
    assert artifacts.validation["connected"] is True


def test_run_design_over_installations_is_connected(tmp_path: Path) -> None:
    """A design whose access nodes are installations validates as connected."""
    artifacts = run_design(
        fixtures.write_solvable_design_paths(tmp_path), DesignParams(min_core_count=2)
    )
    assert artifacts.validation["connected"] is True


def test_run_design_seats_a_forced_location_as_aggregation(tmp_path: Path) -> None:
    """A forced location's fabricated on-net twin is seated on the aggregation tier."""
    design = run_design(
        fixtures.write_solvable_design_paths(tmp_path),
        DesignParams(min_core_count=2, forced_aggregation_names=("A1",)),
    ).design
    assert any(agg.startswith("fac_") for agg in design.aggregation_ids)


def test_run_design_seats_a_forced_off_net_site_as_core(tmp_path: Path) -> None:
    """A forced off-net site is seated as a core via its synthesized local-fiber twin."""
    paths, name = fixtures.write_off_net_solvable_inputs(tmp_path)
    design = run_design(
        paths, DesignParams(min_core_count=2, forced_core_names=(name,))
    ).design
    assert any(core.startswith("offnet_") for core in design.core_ids)


def test_run_design_stitches_regional_edges(tmp_path: Path) -> None:
    """Run design loads regional edge files against the carrier PoP set."""
    vertex_files, edges = fixtures.write_solvable_inputs(tmp_path)
    dcn = tmp_path / "dcn.csv"
    dcn.write_text(
        "name,latitude,longitude,kind,shown_in_map,description\n"
        "R1,42.0,-100.0,ROADM,Not shown in map,\n",
        encoding="utf-8",
    )
    redges = tmp_path / "redges.csv"
    redges.write_text("source,target\nR1,P0\n", encoding="utf-8")
    paths = DesignPaths(vertex_files + (("DCN", dcn),), edges, (redges,))
    artifacts = run_design(paths, fixtures.ring_params())
    assert any(vertex.name == "R1" for vertex in artifacts.vertices)


def test_run_design_rejects_empty_vertices(tmp_path: Path) -> None:
    """Run design rejects vertex files with no rows."""
    empty = tmp_path / "empty.csv"
    empty.write_text(
        "name,latitude,longitude,kind,shown_in_map,description\n", encoding="utf-8"
    )
    paths = DesignPaths((("Lumen", empty),), tmp_path / "e.csv")
    with pytest.raises(ValueError):
        run_design(paths, fixtures.ring_params())
