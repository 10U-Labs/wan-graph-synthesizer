"""Unit tests for the compute-on-demand WAN map service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import fixtures
from wan_designer.model import DesignParams, DesignPaths, PopulationPolicy
from wan_designer.service import available_wan_maps, design_for_wan_map, run_design


def test_run_design_without_augmentation(tmp_path: Path) -> None:
    """Run design without augmentation."""
    vertex_files, edges = fixtures.write_solvable_inputs(tmp_path)
    paths = DesignPaths(vertex_files, edges, None, tmp_path)
    artifacts = run_design(paths, fixtures.ring_params(), False)
    assert artifacts.validation["connected"] is True


def test_run_design_with_augmentation(tmp_path: Path) -> None:
    """Run design augments physical resilience when requested."""
    vertex_files, edges = fixtures.write_solvable_inputs(tmp_path)
    paths = DesignPaths(vertex_files, edges, None, tmp_path)
    artifacts = run_design(paths, fixtures.ring_params(), True)
    assert artifacts.validation["connected"] is True


def test_run_design_anchors_to_population(tmp_path: Path) -> None:
    """Population selection over the two-state scenario yields a connected design."""
    artifacts = run_design(
        fixtures.write_population_inputs(tmp_path), DesignParams(min_core_count=2), False
    )
    assert artifacts.validation["connected"] is True


def test_run_design_scopes_population_to_named_states(tmp_path: Path) -> None:
    """A population_states scope still produces a connected design."""
    params = DesignParams(min_core_count=2, population=PopulationPolicy(states=("CO", "KS")))
    artifacts = run_design(fixtures.write_population_inputs(tmp_path), params, False)
    assert artifacts.validation["connected"] is True


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
    paths = DesignPaths(vertex_files + (("DCN", dcn),), edges, None, tmp_path, (redges,))
    artifacts = run_design(paths, fixtures.ring_params(), False)
    assert any(vertex.name == "R1" for vertex in artifacts.vertices)


def test_run_design_rejects_empty_vertices(tmp_path: Path) -> None:
    """Run design rejects vertex files with no rows."""
    empty = tmp_path / "empty.csv"
    empty.write_text(
        "name,latitude,longitude,kind,shown_in_map,description\n", encoding="utf-8"
    )
    paths = DesignPaths((("Lumen", empty),), tmp_path / "e.csv", None, tmp_path)
    with pytest.raises(ValueError):
        run_design(paths, fixtures.ring_params(), False)


def test_available_wan_maps_defaults_label_to_stem(tmp_path: Path) -> None:
    """A config without a label is listed under its file stem."""
    fixtures.write_solvable_config(tmp_path)
    assert available_wan_maps(tmp_path) == [{"id": "joint", "label": "joint"}]


def test_available_wan_maps_uses_declared_label(tmp_path: Path) -> None:
    """A config's declared label is surfaced over its file stem."""
    (tmp_path / "f_35.yml").write_text("label: F-35\n", encoding="utf-8")
    assert available_wan_maps(tmp_path) == [{"id": "f_35", "label": "F-35"}]


def test_design_for_wan_map_returns_payload(tmp_path: Path) -> None:
    """Computing a known WAN map returns a payload carrying the vertices slice."""
    fixtures.write_solvable_config(tmp_path, min_core_count=2)
    cache: dict[str, Any] = {}
    assert "vertices" in design_for_wan_map(tmp_path, "joint", cache)


def test_design_for_wan_map_caches(tmp_path: Path) -> None:
    """A second request returns the cached payload object, not a recomputation."""
    fixtures.write_solvable_config(tmp_path, min_core_count=2)
    cache: dict[str, Any] = {}
    first = design_for_wan_map(tmp_path, "joint", cache)
    assert design_for_wan_map(tmp_path, "joint", cache) is first


def test_design_for_wan_map_rejects_unknown_id(tmp_path: Path) -> None:
    """An unknown WAN map id raises KeyError before any computation."""
    fixtures.write_solvable_config(tmp_path)
    with pytest.raises(KeyError):
        design_for_wan_map(tmp_path, "nope", {})
