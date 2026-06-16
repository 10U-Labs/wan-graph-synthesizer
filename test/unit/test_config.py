"""Unit tests for loading the YAML configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wan_designer.config import (
    AppConfig,
    config_from_data,
    default_config,
    load_config,
)


def _config(data: dict[str, Any]) -> AppConfig:
    """Resolve a single in-memory config mapping for one test case."""
    return config_from_data(data)


def test_default_min_core_count() -> None:
    """The default config supplies the built-in minimum core count."""
    assert default_config().params.min_core_count == 3


def test_default_has_no_forced_cores() -> None:
    """The default config pins no cores."""
    assert len(default_config().params.forced_core_names) == 0


def test_default_vertex_files() -> None:
    """The default config maps each tenant to its per-tenant vertices CSV."""
    assert ("Lumen", Path("data/vertices/lumen.csv")) in default_config().paths.vertex_files


def test_default_output_dir() -> None:
    """The default config writes outputs to the outputs directory."""
    assert default_config().paths.output_dir == Path("outputs")


def test_default_mapbook_pdf_is_none() -> None:
    """The default config has no source PDF path."""
    assert default_config().paths.mapbook_pdf is None


def test_default_regional_edges() -> None:
    """The default config lists both regional carrier edge files."""
    assert default_config().paths.regional_edge_paths == (
        Path("data/edges/dcn.csv"),
        Path("data/edges/vision_net.csv"),
    )


def test_default_resilience_augmentation_on() -> None:
    """Resilience augmentation defaults on."""
    assert default_config().resilience_augmentation is True


def test_default_label_is_empty() -> None:
    """The default config carries no display label."""
    assert default_config().label == ""


def test_reads_label() -> None:
    """A top-level label is read into the config for the API to surface."""
    assert _config({"label": "Joint"}).label == "Joint"


def test_reads_min_core_count() -> None:
    """A min_core_count value is read from the design section."""
    assert _config({"design": {"min_core_count": 5}}).params.min_core_count == 5


def test_reads_forced_cores() -> None:
    """A forced_cores list is read into the design params."""
    assert _config({"design": {"forced_cores": ["Atlanta, GA"]}}).params.forced_core_names == (
        "Atlanta, GA",
    )


def test_reads_tuning_min_points() -> None:
    """A tuning cluster_min_points value is read into the design params."""
    assert _config({"tuning": {"cluster_min_points": 4}}).params.tuning.cluster_min_points == 4


def test_reads_output_dir() -> None:
    """A top-level output_dir value is read into the paths."""
    assert _config({"output_dir": "out2"}).paths.output_dir == Path("out2")


def test_reads_vertices_mapping() -> None:
    """A vertices tenant->path mapping is read into sorted (tenant, path) pairs."""
    vertices = {"Lumen": "lumen.csv", "F-35": "f_35.csv"}
    assert _config({"inputs": {"vertices": vertices}}).paths.vertex_files == (
        ("F-35", Path("f_35.csv")),
        ("Lumen", Path("lumen.csv")),
    )


def test_rejects_non_mapping_vertices() -> None:
    """A non-mapping vertices value is rejected."""
    with pytest.raises(ValueError):
        _config({"inputs": {"vertices": "single.csv"}})


def test_reads_mapbook_pdf_path() -> None:
    """A non-empty mapbook_pdf input is wrapped as a path."""
    assert _config({"inputs": {"mapbook_pdf": "m.pdf"}}).paths.mapbook_pdf == Path("m.pdf")


def test_reads_resilience_augmentation_off() -> None:
    """Resilience augmentation can be turned off in the design section."""
    assert _config({"design": {"resilience_augmentation": False}}).resilience_augmentation is False


def test_section_must_be_a_mapping() -> None:
    """A non-mapping section is rejected."""
    with pytest.raises(ValueError):
        _config({"design": "not a mapping"})


def test_forced_cores_must_be_a_list() -> None:
    """A non-list forced_cores value is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"forced_cores": "Atlanta, GA"}})


def test_load_config_reads_a_file(tmp_path: Path) -> None:
    """load_config parses the design params from a YAML file."""
    path = tmp_path / "c.yml"
    path.write_text("design:\n  min_core_count: 7\n", encoding="utf-8")
    assert load_config(path).params.min_core_count == 7


def test_load_config_empty_file_uses_defaults(tmp_path: Path) -> None:
    """An empty config file falls back entirely to the defaults."""
    path = tmp_path / "empty.yml"
    path.write_text("", encoding="utf-8")
    assert load_config(path).params.min_core_count == 3


def test_load_config_rejects_malformed_yaml(tmp_path: Path) -> None:
    """Malformed YAML is reported as a ValueError."""
    path = tmp_path / "bad.yml"
    path.write_text("design: [unclosed\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)
