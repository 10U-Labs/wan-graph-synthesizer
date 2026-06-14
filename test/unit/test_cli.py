"""Unit tests for the command-line interface."""

from __future__ import annotations

from pathlib import Path

import pytest

import fixtures
from wan_designer.cli import (
    build_parser,
    cli_paths,
    exit_code_for,
    main,
    params_from_args,
    run_design,
)
from wan_designer.model import CliPaths, ValidationReport


def report(
    *,
    dual_homed: bool = True,
    missing: list[dict[str, str]] | None = None,
    full_mesh: bool = True,
    deficient: list[dict[str, object]] | None = None,
) -> ValidationReport:
    """Build a ValidationReport with all-passing defaults and chosen overrides."""
    return {
        "connected": True,
        "component_count": 1,
        "min_distinct_neighbor_degree": 2,
        "degree_deficient_nodes": deficient or [],
        "biconnected_no_articulation_points": True,
        "articulation_points": [],
        "access_nodes_with_two_aggregation_links": True,
        "aggregations_dual_homed_to_cores": dual_homed,
        "aggregations_missing_core_redundancy": missing or [],
        "cores_full_mesh": full_mesh,
        "core_pairs_disconnected": [],
    }


def test_build_parser_default_core_count() -> None:
    """Build parser default core count."""
    assert build_parser().parse_args([]).core_count == 3


def test_cli_paths_blank_mapbook_becomes_none() -> None:
    """Cli paths blank mapbook becomes none."""
    paths = cli_paths(build_parser().parse_args([]))
    assert paths.mapbook_pdf is None


def test_cli_paths_blank_roles_becomes_none() -> None:
    """Cli paths blank roles becomes none."""
    paths = cli_paths(build_parser().parse_args(["--pop-roles", ""]))
    assert paths.role_path is None


def test_params_from_args_reads_core_count() -> None:
    """Params from args reads core count."""
    args = build_parser().parse_args(["--core-count", "2"])
    assert params_from_args(args).core_count == 2


def test_exit_code_zero_when_all_pass() -> None:
    """Exit code zero when all pass."""
    assert exit_code_for(report()) == 0


def test_exit_code_two_when_not_dual_homed() -> None:
    """Exit code two when not dual homed."""
    failed = report(dual_homed=False, missing=[{"id": "x", "name": "X"}])
    assert exit_code_for(failed) == 2


def test_exit_code_two_when_no_full_mesh() -> None:
    """Exit code two when no full mesh."""
    assert exit_code_for(report(full_mesh=False)) == 2


def test_exit_code_two_when_degree_deficient() -> None:
    """Exit code two when degree deficient."""
    failed = report(deficient=[{"id": "x", "name": "X", "degree": 1}])
    assert exit_code_for(failed) == 2


def test_run_design_without_augmentation(tmp_path: Path) -> None:
    """Run design without augmentation."""
    kml, edges = fixtures.write_solvable_inputs(tmp_path)
    paths = CliPaths(kml, edges, None, None, tmp_path)
    artifacts = run_design(paths, fixtures.ring_params(), False)
    assert artifacts.validation["connected"] is True


def test_run_design_stitches_regional_carriers(tmp_path: Path) -> None:
    """Run design stitches regional carriers onto the Lumen graph."""
    kml, edges = fixtures.write_solvable_inputs(tmp_path)
    rnodes = tmp_path / "rnodes.csv"
    rnodes.write_text("name,lat,lon,network\nR1,41.0,-100.0,dcn\n", encoding="utf-8")
    redges = tmp_path / "redges.csv"
    redges.write_text("source,target,type\nR1,P0,interconnect\n", encoding="utf-8")
    paths = CliPaths(kml, edges, None, None, tmp_path, rnodes, (redges,))
    artifacts = run_design(paths, fixtures.ring_params(), False)
    assert any(node.name == "R1" for node in artifacts.nodes)


def test_main_succeeds_on_solvable_inputs(tmp_path: Path) -> None:
    """Main succeeds on solvable inputs."""
    kml, edges = fixtures.write_solvable_inputs(tmp_path)
    args = fixtures.design_args(
        kml,
        edges,
        tmp_path / "out",
        extra=["--core-count", "2"],
    )
    assert main(args) == 0


def test_main_returns_one_on_missing_input(tmp_path: Path) -> None:
    """Main returns one on missing input."""
    assert main([str(tmp_path / "nope.kml")]) == 1


def test_run_design_rejects_empty_document(tmp_path: Path) -> None:
    """Run design rejects empty document."""
    kml = tmp_path / "empty.kml"
    kml.write_text(
        '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2">'
        "<Document><name>x</name></Document></kml>",
        encoding="utf-8",
    )
    paths = CliPaths(kml, tmp_path / "e.csv", None, None, tmp_path)
    with pytest.raises(ValueError):
        run_design(paths, fixtures.ring_params(), False)
