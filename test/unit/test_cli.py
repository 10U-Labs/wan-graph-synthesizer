"""Unit tests for the command-line interface."""

from __future__ import annotations

from pathlib import Path

import pytest

import fixtures
from wan_designer.cli import (
    build_parser,
    exit_code_for,
    load_app_config,
    main,
    resolve_paths,
    resolve_params,
    run_design,
)
from wan_designer.config import default_config
from wan_designer.model import CliPaths, DesignParams, ValidationReport


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
        "degree_deficient_vertices": deficient or [],
        "biconnected_no_articulation_points": True,
        "articulation_points": [],
        "access_vertices_with_two_aggregation_links": True,
        "aggregations_dual_homed_to_cores": dual_homed,
        "aggregations_missing_core_redundancy": missing or [],
        "cores_full_mesh": full_mesh,
        "core_pairs_disconnected": [],
    }


def _params(argv: list[str]) -> DesignParams:
    """Resolve design params from argv against the built-in default config."""
    return resolve_params(default_config(), build_parser().parse_args(argv))


def _paths(argv: list[str]) -> CliPaths:
    """Resolve file paths from argv against the built-in default config."""
    return resolve_paths(default_config(), build_parser().parse_args(argv))


def test_build_parser_default_core_count_is_unset() -> None:
    """With no flag the parser leaves core count unset so the config can supply it."""
    assert build_parser().parse_args([]).core_count is None


def test_resolve_params_default_core_count() -> None:
    """The default config supplies the core count when no flag is given."""
    assert _params([]).core_count == 3


def test_resolve_params_core_count_override() -> None:
    """A core-count flag overrides the config value."""
    assert _params(["--core-count", "2"]).core_count == 2


def test_resolve_params_force_core_override() -> None:
    """A force-core flag replaces the config's forced cores."""
    assert _params(["--force-core", "Denver, CO"]).forced_core_names == ("Denver, CO",)


def test_resolve_params_force_aggregation_override() -> None:
    """A force-aggregation flag replaces the config's forced aggregations."""
    assert _params(["--force-aggregation", "Herndon"]).forced_aggregation_names == ("Herndon",)


def test_resolve_params_exclude_override() -> None:
    """An exclude flag replaces the config's exclusions."""
    assert _params(["--exclude", "Ogden"]).excluded_names == ("Ogden",)


def test_resolve_params_allow_roadm_flag() -> None:
    """The allow-roadm flag turns the option on over the config default."""
    assert _params(["--allow-roadm-aggregation"]).allow_roadm_aggregation is True


def test_resolve_paths_blank_mapbook_pdf_is_none() -> None:
    """The default config's empty mapbook PDF resolves to no path."""
    assert _paths([]).mapbook_pdf is None


def test_resolve_paths_mapbook_pdf_override() -> None:
    """A non-empty mapbook-pdf flag overrides the config path."""
    assert _paths(["--mapbook-pdf", "m.pdf"]).mapbook_pdf == Path("m.pdf")


def test_resolve_paths_empty_mapbook_pdf_disables() -> None:
    """An explicit empty mapbook-pdf flag disables the path."""
    assert _paths(["--mapbook-pdf", ""]).mapbook_pdf is None


def test_resolve_paths_input_override() -> None:
    """A positional input overrides the config's vertices file."""
    assert _paths(["some.csv"]).vertices_path == Path("some.csv")


def test_resolve_paths_keeps_default_input() -> None:
    """With no positional the config's vertices path is kept."""
    assert _paths([]).vertices_path == Path("data/vertices.csv")


def test_resolve_paths_regional_edges_override() -> None:
    """A regional-edges flag replaces the config's regional edge files."""
    edges = _paths(["--regional-edges", "a.csv", "b.csv"]).regional_edge_paths
    assert edges == (Path("a.csv"), Path("b.csv"))


def test_resolve_paths_keeps_default_regional_edges() -> None:
    """With no flag the config's regional edge files are kept."""
    edges = _paths([]).regional_edge_paths
    assert edges == (
        Path("data/edges/dcn_edges.csv"),
        Path("data/edges/vision_net_edges.csv"),
    )


def test_load_app_config_without_flag_is_default() -> None:
    """Omitting --config yields the built-in default configuration."""
    assert load_app_config(build_parser().parse_args([])) == default_config()


def test_load_app_config_reads_named_file(tmp_path: Path) -> None:
    """A --config flag loads and resolves the named YAML file."""
    cfg = tmp_path / "c.yml"
    cfg.write_text("design:\n  core_count: 5\n", encoding="utf-8")
    loaded = load_app_config(build_parser().parse_args(["--config", str(cfg)]))
    assert loaded.params.core_count == 5


def test_build_parser_collects_repeated_force_core() -> None:
    """The force-core flag accumulates each PoP name it is given."""
    args = build_parser().parse_args(["--force-core", "Ashburn, VA", "--force-core", "El Paso, TX"])
    assert args.force_core == ["Ashburn, VA", "El Paso, TX"]


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
    vertices_csv, edges = fixtures.write_solvable_inputs(tmp_path)
    paths = CliPaths(vertices_csv, edges, None, tmp_path)
    artifacts = run_design(paths, fixtures.ring_params(), False)
    assert artifacts.validation["connected"] is True


def test_run_design_stitches_regional_edges(tmp_path: Path) -> None:
    """Run design loads regional edge files against the carrier PoP set."""
    vertices_csv = tmp_path / "vertices.csv"
    vertices_csv.write_text(
        fixtures.solvable_vertices_csv() + "R1,42.0,-100.0,DCN,ROADM,Not shown in map,\n",
        encoding="utf-8",
    )
    edges = tmp_path / "edges.csv"
    edges.write_text(fixtures.solvable_edges_csv(), encoding="utf-8")
    redges = tmp_path / "redges.csv"
    redges.write_text("source,target\nR1,P0\n", encoding="utf-8")
    paths = CliPaths(vertices_csv, edges, None, tmp_path, (redges,))
    artifacts = run_design(paths, fixtures.ring_params(), False)
    assert any(vertex.name == "R1" for vertex in artifacts.vertices)


def test_main_succeeds_on_solvable_inputs(tmp_path: Path) -> None:
    """Main succeeds on solvable inputs."""
    vertices_csv, edges = fixtures.write_solvable_inputs(tmp_path)
    args = fixtures.design_args(
        vertices_csv,
        edges,
        tmp_path / "out",
        extra=["--core-count", "2"],
    )
    assert main(args) == 0


def test_main_returns_one_on_missing_input(tmp_path: Path) -> None:
    """Main returns one on missing input."""
    assert main([str(tmp_path / "nope.csv")]) == 1


def test_main_honors_config_file(tmp_path: Path) -> None:
    """Main reads the design parameters from a --config file."""
    vertices_csv, edges = fixtures.write_solvable_inputs(tmp_path)
    cfg = tmp_path / "config.yml"
    cfg.write_text("design:\n  core_count: 2\n", encoding="utf-8")
    args = fixtures.design_args(vertices_csv, edges, tmp_path / "out", extra=["--config", str(cfg)])
    assert main(args) == 0


def test_run_design_rejects_empty_vertices(tmp_path: Path) -> None:
    """Run design rejects a vertices file with no rows."""
    vertices_csv = tmp_path / "empty.csv"
    vertices_csv.write_text(
        "name,latitude,longitude,tenant,kind,shown_in_map,description\n", encoding="utf-8"
    )
    paths = CliPaths(vertices_csv, tmp_path / "e.csv", None, tmp_path)
    with pytest.raises(ValueError):
        run_design(paths, fixtures.ring_params(), False)
