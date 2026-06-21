"""Unit tests for loading the YAML configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wan_designer.config import AppConfig, app_config_from_parts, config_from_data
from wan_graph.model import ForcedConnection


# The three redundancy degrees are required (no default); inject them so each test
# can focus on the field under test without restating them.
_REQUIRED_DEGREES = {
    "core_links_per_core": 3,
    "aggregation_homing_degree": 2,
    "access_aggregation_links": 2,
}


def _config(data: dict[str, Any]) -> AppConfig:
    """Resolve a single in-memory config mapping (with required degrees) for one test."""
    merged = dict(data)
    merged["tuning"] = {**_REQUIRED_DEGREES, **data.get("tuning", {})}
    return config_from_data(merged)


def default_config() -> AppConfig:
    """The built-in configuration: required degrees only, everything else defaulted."""
    return _config({})


def test_default_min_core_count() -> None:
    """The default config supplies the built-in minimum core count."""
    assert default_config().params.min_core_count == 3


def test_default_has_no_forced_cores() -> None:
    """The default config pins no cores."""
    assert len(default_config().params.forced_core_names) == 0


def test_default_max_core_count_is_none() -> None:
    """The default config leaves the core tier uncapped."""
    assert default_config().params.max_core_count is None


def test_default_vertex_files() -> None:
    """The default config maps each tenant to its per-tenant vertices CSV."""
    lumen = ("Lumen", Path("data/vertices/carriers/lumen.csv"))
    assert lumen in default_config().paths.vertex_files


def test_default_regional_edges() -> None:
    """The default config lists both regional carrier edge files."""
    assert default_config().paths.regional_edge_paths == (
        Path("data/edges/dcn.csv"),
        Path("data/edges/vision_net.csv"),
    )


def test_default_off_net_path_is_none() -> None:
    """The default config configures no off-net site file."""
    assert default_config().paths.off_net_path is None


def test_reads_off_net_path() -> None:
    """An inputs.off_net value is read into the design paths."""
    assert _config({"inputs": {"off_net": "off.csv"}}).paths.off_net_path == Path("off.csv")


def test_default_label_is_empty() -> None:
    """The default config carries no display label."""
    assert default_config().label == ""


def test_reads_label() -> None:
    """A top-level label is read into the config for the API to surface."""
    assert _config({"label": "Joint"}).label == "Joint"


def test_reads_min_core_count() -> None:
    """A min_core_count value is read from the design section."""
    assert _config({"design": {"min_core_count": 5}}).params.min_core_count == 5


def test_reads_max_core_count() -> None:
    """A max_core_count value is read from the design section."""
    assert _config({"design": {"max_core_count": 7}}).params.max_core_count == 7


def test_default_access_aggregation_links() -> None:
    """The default config homes each access vertex to two aggregations."""
    assert default_config().params.tuning.access_aggregation_links == 2


def test_reads_access_aggregation_links() -> None:
    """An access_aggregation_links value is read from the tuning section."""
    assert _config(
        {"tuning": {"access_aggregation_links": 3}}
    ).params.tuning.access_aggregation_links == 3


def test_default_core_links_per_core_is_three() -> None:
    """The default config wires each core to three other cores on the backbone."""
    assert default_config().params.tuning.core_links_per_core == 3


def test_reads_core_links_per_core() -> None:
    """A core_links_per_core value is read into the tuning."""
    assert _config(
        {"tuning": {"core_links_per_core": 4}}
    ).params.tuning.core_links_per_core == 4


def test_reads_forced_cores() -> None:
    """A forced_cores list is read into the design params."""
    assert _config({"design": {"forced_cores": ["Atlanta, GA"]}}).params.forced_core_names == (
        "Atlanta, GA",
    )


def test_default_has_no_forced_connections() -> None:
    """The default config pins no connections."""
    assert len(default_config().forced_connections) == 0


def test_reads_forced_connections() -> None:
    """A forced_connections list is parsed into ForcedConnection entries."""
    connection = {"source": "Dallas, TX", "target": "Denver, CO", "type": "core-core"}
    assert _config({"design": {"forced_connections": [connection]}}).forced_connections == (
        ForcedConnection("core-core", "Dallas, TX", "Denver, CO"),
    )


def test_forced_connections_must_be_a_list() -> None:
    """A non-list forced_connections value is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"forced_connections": {"source": "A"}}})


def test_forced_connection_must_be_a_mapping() -> None:
    """A forced_connections entry that is not a mapping is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"forced_connections": ["Dallas, TX"]}})


def test_forced_connection_requires_all_keys() -> None:
    """A forced_connections entry missing a key is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"forced_connections": [{"source": "A", "target": "B"}]}})


def test_forced_connection_rejects_unknown_type() -> None:
    """A forced_connections entry with an unsupported type is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"forced_connections": [{"source": "A", "target": "B", "type": "x"}]}})


def test_default_has_no_excluded_connections() -> None:
    """The default config prunes no core-core mesh links."""
    assert len(default_config().excluded_connections) == 0


def test_reads_excluded_connections() -> None:
    """An excluded_connections entry defaults to a pruned core-core pair."""
    design = {"excluded_connections": [{"source": "Seattle, WA", "target": "Boise, ID"}]}
    assert _config({"design": design}).excluded_connections == (
        ForcedConnection("core-core", "Seattle, WA", "Boise, ID"),
    )


def test_excluded_connection_rejects_a_non_core_core_type() -> None:
    """An excluded_connections entry of a non-core-core type is rejected."""
    bad = {"source": "A", "target": "B", "type": "aggregation-core"}
    with pytest.raises(ValueError):
        _config({"design": {"excluded_connections": [bad]}})


def test_default_has_no_prohibited_aggregations() -> None:
    """The default config bars no PoP from the aggregation tier."""
    assert len(default_config().params.exclusions.prohibited_aggregation_names) == 0


def test_reads_prohibited_aggregations() -> None:
    """A prohibited_aggregations list is read into the design params."""
    design = {"prohibited_aggregations": ["Denver, CO", "Boise, ID"]}
    assert _config({"design": design}).params.exclusions.prohibited_aggregation_names == (
        "Denver, CO",
        "Boise, ID",
    )


def test_prohibited_aggregations_must_be_a_list_of_strings() -> None:
    """A prohibited_aggregations value that is not a list of strings is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"prohibited_aggregations": "Denver, CO"}})


def test_default_has_no_prohibited_cores() -> None:
    """The default config bars no PoP from the core tier."""
    assert len(default_config().params.exclusions.prohibited_core_names) == 0


def test_reads_prohibited_cores() -> None:
    """A prohibited_cores list is read into the design params."""
    design = {"prohibited_cores": ["Denver, CO", "Boise, ID"]}
    assert _config({"design": design}).params.exclusions.prohibited_core_names == (
        "Denver, CO",
        "Boise, ID",
    )


def test_prohibited_cores_must_be_a_list_of_strings() -> None:
    """A prohibited_cores value that is not a list of strings is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"prohibited_cores": "Denver, CO"}})


def test_reads_tuning_min_points() -> None:
    """A tuning cluster_min_points value is read into the design params."""
    assert _config({"tuning": {"cluster_min_points": 4}}).params.tuning.cluster.min_points == 4


def test_reads_tuning_cluster_k() -> None:
    """A tuning cluster_k value is read into the design params."""
    assert _config({"tuning": {"cluster_k": 3}}).params.tuning.cluster.k == 3


def test_reads_vertices_mapping() -> None:
    """A vertices tenant->path mapping is read into sorted (tenant, path) pairs."""
    vertices = {"Lumen": "lumen.csv", "F-35": "f_35.csv"}
    assert _config({"inputs": {"vertices": vertices}}).paths.vertex_files == (
        ("F-35", Path("f_35.csv")),
        ("Lumen", Path("lumen.csv")),
    )


def test_reads_vertices_list_of_paths() -> None:
    """A tenant mapped to a list expands into one (tenant, path) pair per entry."""
    vertices = {"AWS": ["aws_secret.csv", "aws_top_secret.csv"]}
    assert _config({"inputs": {"vertices": vertices}}).paths.vertex_files == (
        ("AWS", Path("aws_secret.csv")),
        ("AWS", Path("aws_top_secret.csv")),
    )


def test_rejects_non_string_path_in_list() -> None:
    """A vertices list containing a non-string path is rejected."""
    with pytest.raises(ValueError):
        _config({"inputs": {"vertices": {"AWS": ["aws.csv", 3]}}})


def test_rejects_non_mapping_vertices() -> None:
    """A non-mapping vertices value is rejected."""
    with pytest.raises(ValueError):
        _config({"inputs": {"vertices": "single.csv"}})


def test_missing_required_degree_is_rejected() -> None:
    """A config whose tuning omits a required redundancy degree is rejected."""
    with pytest.raises(ValueError):
        config_from_data({"tuning": {"core_links_per_core": 3, "access_aggregation_links": 2}})


def test_reads_aggregation_homing_degree() -> None:
    """An aggregation_homing_degree value is read into the tuning."""
    assert _config(
        {"tuning": {"aggregation_homing_degree": 1}}
    ).params.tuning.aggregation_homing_degree == 1


def test_section_must_be_a_mapping() -> None:
    """A non-mapping section is rejected."""
    with pytest.raises(ValueError):
        _config({"design": "not a mapping"})


def test_forced_cores_must_be_a_list() -> None:
    """A non-list forced_cores value is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"forced_cores": "Atlanta, GA"}})


def _parts(**overrides: Any) -> dict[str, Any]:
    """A full set of per-resource customer documents for the assembler."""
    parts: dict[str, Any] = {
        "forced-core-nodes": [],
        "forced-aggregation-points": [],
        "forced-connections": [],
        "prohibited-core-nodes": [],
        "prohibited-aggregation-points": [],
        "prohibited-connections": [],
        "core-node-count": {"min": 3, "max": 5},
        "core-mesh-degree": {"degree": 3},
        "aggregation-homing-degree": {"degree": 2},
        "access-homing-degree": {"degree": 1},
        "knobs": {"compass_octants": 8},
        "label": {"label": "Joint"},
    }
    parts.update(overrides)
    return parts


def test_app_config_from_parts_assembles_degrees_and_label() -> None:
    """The assembler reads the three degrees and the label from their documents."""
    config = app_config_from_parts(_parts())
    assert config.params.tuning.core_links_per_core == 3
    assert config.params.tuning.aggregation_homing_degree == 2
    assert config.params.tuning.access_aggregation_links == 1
    assert config.label == "Joint"


def test_app_config_from_parts_reads_core_node_count() -> None:
    """The assembler reads min and max core count from the core-node-count document."""
    config = app_config_from_parts(_parts())
    assert config.params.min_core_count == 3
    assert config.params.max_core_count == 5


def test_app_config_from_parts_requires_each_degree() -> None:
    """A missing degree document is rejected by the assembler."""
    parts = _parts()
    del parts["aggregation-homing-degree"]
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_parses_connections() -> None:
    """Forced and prohibited connection documents are parsed into the config."""
    parts = _parts(
        **{
            "forced-connections": [{"source": "A", "target": "B", "type": "core-core"}],
            "prohibited-connections": [{"source": "C", "target": "D"}],
        }
    )
    config = app_config_from_parts(parts)
    assert config.forced_connections == (ForcedConnection("core-core", "A", "B"),)
    assert config.excluded_connections == (ForcedConnection("core-core", "C", "D"),)
