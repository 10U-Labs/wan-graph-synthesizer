"""Unit tests for resolving the WAN designer configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from synthesizer.config import AppConfig, app_config_from_parts, config_from_data
from synthesizer.model import ForcedConnection


# The two redundancy degrees and the coverage target are required (no default); inject
# them so each test can focus on the field under test without restating them.
_REQUIRED_TUNING = {
    "backbone_mesh_degree": 3,
    "access_backbone_links": 2,
    "backbone_coverage_target_miles": 600.0,
}


def _config(data: dict[str, Any]) -> AppConfig:
    """Resolve a single in-memory config mapping (with required fields) for one test.

    ``restrict_backbone_to_data_centers`` (like the two redundancy degrees) is required
    with no default, so it is injected into the design section unless the test overrides
    it -- letting each test focus on the field under test. A non-mapping ``design`` is
    passed through so the "section must be a mapping" rejection still fires.
    """
    merged = dict(data)
    merged["tuning"] = {**_REQUIRED_TUNING, **data.get("tuning", {})}
    design = data.get("design", {})
    if isinstance(design, dict):
        merged["design"] = {
            "restrict_backbone_to_data_centers": True,
            "promote_high_degree_convergences_to_backbone_nodes": True,
            **design,
        }
    return config_from_data(merged)


def default_config() -> AppConfig:
    """The built-in configuration: required degrees only, everything else defaulted."""
    return _config({})


def test_default_min_backbone_count() -> None:
    """The default config supplies the built-in minimum backbone count."""
    assert default_config().params.min_backbone_count == 3


def test_default_has_no_forced_backbone() -> None:
    """The default config pins no backbone nodes."""
    assert len(default_config().params.forced_backbone_names) == 0


def test_default_max_backbone_count_is_none() -> None:
    """The default config leaves the backbone uncapped."""
    assert default_config().params.max_backbone_count is None


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
    assert _config({"label": "Minuteman"}).label == "Minuteman"


def test_reads_min_backbone_count() -> None:
    """A min_backbone_count value is read from the design section."""
    assert _config({"design": {"min_backbone_count": 5}}).params.min_backbone_count == 5


def test_reads_max_backbone_count() -> None:
    """A max_backbone_count value is read from the design section."""
    assert _config({"design": {"max_backbone_count": 7}}).params.max_backbone_count == 7


def test_default_access_backbone_links() -> None:
    """The default config homes each demand vertex to two backbone nodes."""
    assert default_config().params.tuning.access_backbone_links == 2


def test_reads_access_backbone_links() -> None:
    """An access_backbone_links value is read from the tuning section."""
    assert _config(
        {"tuning": {"access_backbone_links": 3}}
    ).params.tuning.access_backbone_links == 3


def test_default_backbone_mesh_degree_is_three() -> None:
    """The default config wires each backbone node to three others on the mesh."""
    assert default_config().params.tuning.backbone_mesh_degree == 3


def test_reads_backbone_mesh_degree() -> None:
    """A backbone_mesh_degree value is read into the tuning."""
    assert _config(
        {"tuning": {"backbone_mesh_degree": 4}}
    ).params.tuning.backbone_mesh_degree == 4


def test_reads_forced_backbone() -> None:
    """A forced_backbone list is read into the design params."""
    assert _config(
        {"design": {"forced_backbone": ["Atlanta, GA"]}}
    ).params.forced_backbone_names == ("Atlanta, GA",)


def test_default_has_no_forced_connections() -> None:
    """The default config pins no connections."""
    assert len(default_config().forced_connections) == 0


def test_reads_forced_connections() -> None:
    """A forced_connections list is parsed into ForcedConnection entries."""
    connection = {"source": "Dallas, TX", "target": "Denver, CO", "type": "backbone-backbone"}
    assert _config({"design": {"forced_connections": [connection]}}).forced_connections == (
        ForcedConnection("backbone-backbone", "Dallas, TX", "Denver, CO"),
    )


def test_forced_connections_must_be_a_list() -> None:
    """A non-list forced_connections value is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"forced_connections": {"source": "A"}}})


def test_forced_connection_must_be_a_mapping() -> None:
    """A forced_connections entry that is not a mapping is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"forced_connections": ["Dallas, TX"]}})


def test_forced_connection_requires_a_type() -> None:
    """A forced_connections entry missing its required type is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"forced_connections": [{"source": "A", "target": "B"}]}})


def test_forced_connection_rejects_unknown_type() -> None:
    """A forced_connections entry with an unsupported type is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"forced_connections": [{"source": "A", "target": "B", "type": "x"}]}})


def test_default_has_no_excluded_connections() -> None:
    """The default config prunes no backbone-backbone mesh links."""
    assert len(default_config().excluded_connections) == 0


def test_reads_excluded_connections() -> None:
    """An excluded_connections entry defaults to a pruned backbone-backbone pair."""
    design = {"excluded_connections": [{"source": "Seattle, WA", "target": "Boise, ID"}]}
    assert _config({"design": design}).excluded_connections == (
        ForcedConnection("backbone-backbone", "Seattle, WA", "Boise, ID"),
    )


def test_excluded_connection_rejects_a_non_backbone_type() -> None:
    """An excluded_connections entry of a non-backbone-backbone type is rejected."""
    bad = {"source": "A", "target": "B", "type": "access-backbone"}
    with pytest.raises(ValueError):
        _config({"design": {"excluded_connections": [bad]}})


def test_default_has_no_prohibited_backbone() -> None:
    """The default config bars no PoP from the backbone."""
    assert len(default_config().params.exclusions.prohibited_backbone_names) == 0


def test_reads_restrict_backbone_to_data_centers_true() -> None:
    """A restrict_backbone_to_data_centers=true design gates the backbone to data centers."""
    assert _config(
        {"design": {"restrict_backbone_to_data_centers": True}}
    ).restrict_backbone_to_datacenters is True


def test_reads_restrict_backbone_to_data_centers_false() -> None:
    """A restrict_backbone_to_data_centers=false design opens the backbone to any city."""
    assert _config(
        {"design": {"restrict_backbone_to_data_centers": False}}
    ).restrict_backbone_to_datacenters is False


def test_restrict_backbone_to_data_centers_must_be_a_boolean() -> None:
    """A non-boolean restrict_backbone_to_data_centers value is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"restrict_backbone_to_data_centers": "yes"}})


def test_restrict_backbone_to_data_centers_is_required() -> None:
    """A design omitting restrict_backbone_to_data_centers is rejected (no default)."""
    with pytest.raises(ValueError):
        config_from_data({"tuning": _REQUIRED_TUNING})


def test_reads_promote_high_degree_convergences_true() -> None:
    """A promote...=true design lets the convergence pass seat high-degree hubs."""
    assert _config(
        {"design": {"promote_high_degree_convergences_to_backbone_nodes": True}}
    ).params.promote_high_degree_convergences is True


def test_reads_promote_high_degree_convergences_false() -> None:
    """A promote...=false design turns the convergence promotion pass off."""
    assert _config(
        {"design": {"promote_high_degree_convergences_to_backbone_nodes": False}}
    ).params.promote_high_degree_convergences is False


def test_promote_high_degree_convergences_must_be_a_boolean() -> None:
    """A non-boolean promote_high_degree_convergences_to_backbone_nodes value is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"promote_high_degree_convergences_to_backbone_nodes": "yes"}})


def test_promote_high_degree_convergences_is_required() -> None:
    """A design omitting promote_high_degree_convergences_to_backbone_nodes is rejected."""
    with pytest.raises(ValueError):
        config_from_data(
            {
                "tuning": _REQUIRED_TUNING,
                "design": {"restrict_backbone_to_data_centers": True},
            }
        )


def test_reads_prohibited_backbone() -> None:
    """A prohibited_backbone list is read into the design params."""
    design = {"prohibited_backbone": ["Denver, CO", "Boise, ID"]}
    assert _config({"design": design}).params.exclusions.prohibited_backbone_names == (
        "Denver, CO",
        "Boise, ID",
    )


def test_prohibited_backbone_must_be_a_list_of_strings() -> None:
    """A prohibited_backbone value that is not a list of strings is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"prohibited_backbone": "Denver, CO"}})


def test_reads_settings_compass_octants() -> None:
    """A settings compass_octants value is read into the design params."""
    assert _config({"settings": {"compass_octants": 6}}).params.tuning.compass_octants == 6


def test_reads_tuning_coverage_target() -> None:
    """A tuning backbone_coverage_target_miles value is read into the design params."""
    assert _config(
        {"tuning": {"backbone_coverage_target_miles": 250.0}}
    ).params.tuning.backbone_coverage_target_miles == 250.0


def test_reads_settings_enum_memory_fraction() -> None:
    """A settings enum_memory_fraction value is read into the enumeration budget."""
    assert _config(
        {"settings": {"enum_memory_fraction": 0.3}}
    ).params.tuning.enum_budget.memory_fraction == 0.3


def test_reads_settings_backbone_set_peak_bytes() -> None:
    """A settings backbone_set_peak_bytes value is read into the enumeration budget."""
    assert _config(
        {"settings": {"backbone_set_peak_bytes": 200}}
    ).params.tuning.enum_budget.set_peak_bytes == 200


def test_a_dial_left_in_the_tuning_section_is_not_read() -> None:
    """A dial left in the tuning section is ignored, so the built-in default stands."""
    assert _config({"tuning": {"compass_octants": 6}}).params.tuning.compass_octants == 8


def test_reads_vertices_mapping() -> None:
    """A vertices tenant->path mapping is read into sorted (tenant, path) pairs."""
    vertices = {"Lumen": "lumen.csv", "F-35": "f_35.csv"}
    assert _config({"inputs": {"vertices": vertices}}).paths.vertex_files == (
        ("F-35", Path("f_35.csv")),
        ("Lumen", Path("lumen.csv")),
    )


def test_reads_vertices_list_of_paths() -> None:
    """A tenant mapped to a list expands into one (tenant, path) pair per entry."""
    vertices = {"Providers": ["region_a.csv", "region_b.csv"]}
    assert _config({"inputs": {"vertices": vertices}}).paths.vertex_files == (
        ("Providers", Path("region_a.csv")),
        ("Providers", Path("region_b.csv")),
    )


def test_reads_carrier_edges_path() -> None:
    """An inputs.carrier_edges value is read into the design paths."""
    assert _config(
        {"inputs": {"carrier_edges": "fiber.csv"}}
    ).paths.edge_path == Path("fiber.csv")


def test_rejects_non_string_path_in_list() -> None:
    """A vertices list containing a non-string path is rejected."""
    with pytest.raises(ValueError):
        _config({"inputs": {"vertices": {"Providers": ["region_a.csv", 3]}}})


def test_rejects_non_mapping_vertices() -> None:
    """A non-mapping vertices value is rejected."""
    with pytest.raises(ValueError):
        _config({"inputs": {"vertices": "single.csv"}})


def test_rejects_non_list_regional_edges() -> None:
    """A non-list regional_edges value is rejected."""
    with pytest.raises(ValueError):
        _config({"inputs": {"regional_edges": "single.csv"}})


def test_missing_required_degree_is_rejected() -> None:
    """A config whose tuning omits a required redundancy degree is rejected."""
    with pytest.raises(ValueError):
        config_from_data(
            {"tuning": {"backbone_mesh_degree": 3, "backbone_coverage_target_miles": 600.0}}
        )


def test_non_integer_degree_is_rejected() -> None:
    """A required degree that is not an integer is rejected."""
    with pytest.raises(ValueError):
        config_from_data(
            {"tuning": {"backbone_mesh_degree": "three", "access_backbone_links": 2}}
        )


def test_boolean_degree_is_rejected() -> None:
    """A required degree given as a bool (an int subclass) is rejected."""
    with pytest.raises(ValueError):
        config_from_data(
            {"tuning": {"backbone_mesh_degree": True, "access_backbone_links": 2}}
        )


def test_missing_coverage_target_is_rejected() -> None:
    """A config whose tuning omits the required coverage target is rejected."""
    with pytest.raises(ValueError):
        config_from_data(
            {
                "tuning": {"backbone_mesh_degree": 3, "access_backbone_links": 2},
                "design": {"restrict_backbone_to_data_centers": True},
            }
        )


def test_non_number_coverage_target_is_rejected() -> None:
    """A coverage target that is not a number is rejected."""
    with pytest.raises(ValueError):
        _config({"tuning": {"backbone_coverage_target_miles": "far"}})


def test_section_must_be_a_mapping() -> None:
    """A non-mapping section is rejected."""
    with pytest.raises(ValueError):
        _config({"design": "not a mapping"})


def test_forced_backbone_must_be_a_list() -> None:
    """A non-list forced_backbone value is rejected."""
    with pytest.raises(ValueError):
        _config({"design": {"forced_backbone": "Atlanta, GA"}})


def _parts(**overrides: Any) -> dict[str, Any]:
    """A full set of per-resource tenant documents for the assembler."""
    parts: dict[str, Any] = {
        "forced-backbone-nodes": [],
        "forced-connections": [],
        "prohibited-backbone-nodes": [],
        "prohibited-connections": [],
        "backbone-node-count": {"min": 3, "max": 5},
        "backbone-mesh-degree": {"degree": 3},
        "access-homing-degree": {"degree": 2},
        "backbone-placement": {"restrict": True},
        "convergence-promotion": {"promote": True},
        "knobs": {"backbone_coverage_target_miles": 600.0},
        "label": {"label": "Minuteman"},
    }
    parts.update(overrides)
    return parts


def test_app_config_from_parts_folds_settings_into_tuning() -> None:
    """A settings document supplies tuning values alongside the knobs document."""
    parts = _parts(settings={"enum_memory_fraction": 0.25})
    budget = app_config_from_parts(parts).params.tuning.enum_budget
    assert budget.memory_fraction == 0.25


def test_app_config_from_parts_reads_every_dial_from_settings() -> None:
    """The three implementation dials come from the settings document."""
    parts = _parts(settings={
        "compass_octants": 4, "enum_memory_fraction": 0.25, "backbone_set_peak_bytes": 320,
    })
    budget = app_config_from_parts(parts).params.tuning.enum_budget
    assert (budget.memory_fraction, budget.set_peak_bytes) == (0.25, 320)


def test_app_config_from_parts_ignores_a_dial_left_in_knobs() -> None:
    """A dial an operator left behind under knobs no longer steers the search."""
    parts = _parts(knobs={"backbone_coverage_target_miles": 600.0, "compass_octants": 4})
    assert app_config_from_parts(parts).params.tuning.compass_octants == 8


def test_app_config_from_parts_without_settings_is_unchanged() -> None:
    """A tenant carrying no settings document parses exactly as it did before."""
    assert app_config_from_parts(_parts()) == app_config_from_parts(_parts(settings={}))


def test_app_config_from_parts_assembles_the_two_degrees() -> None:
    """The assembler reads both redundancy degrees from their documents."""
    tuning = app_config_from_parts(_parts()).params.tuning
    assert (tuning.backbone_mesh_degree, tuning.access_backbone_links) == (3, 2)


def test_app_config_from_parts_reads_the_label() -> None:
    """The assembler reads the display label from the label document."""
    assert app_config_from_parts(_parts()).label == "Minuteman"


def test_app_config_from_parts_reads_a_plain_label() -> None:
    """A label document that is a bare string (not a mapping) is read as the label."""
    assert app_config_from_parts(_parts(label="Bare")).label == "Bare"


def test_app_config_from_parts_reads_backbone_node_count() -> None:
    """The assembler reads min and max from the backbone-node-count document."""
    params = app_config_from_parts(_parts()).params
    assert (params.min_backbone_count, params.max_backbone_count) == (3, 5)


def test_app_config_from_parts_reads_forced_backbone() -> None:
    """The assembler reads the forced-backbone-nodes document into the params."""
    parts = _parts(**{"forced-backbone-nodes": ["Denver, CO"]})
    assert app_config_from_parts(parts).params.forced_backbone_names == ("Denver, CO",)


def test_app_config_from_parts_requires_each_degree() -> None:
    """A missing degree document is rejected by the assembler."""
    parts = _parts()
    del parts["access-homing-degree"]
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_requires_coverage_target() -> None:
    """A knobs document omitting the coverage target is rejected by the assembler."""
    parts = _parts(knobs={"compass_octants": 8})
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_rejects_a_malformed_degree_document() -> None:
    """A degree document that is not a ``{"degree": int}`` object is rejected."""
    parts = _parts()
    parts["backbone-mesh-degree"] = 3
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_rejects_a_non_integer_degree() -> None:
    """A degree document whose value is not an integer is rejected."""
    parts = _parts()
    parts["backbone-mesh-degree"] = {"degree": "three"}
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_defaults_count_when_absent() -> None:
    """An empty backbone-node-count document leaves min/max at their built-in defaults."""
    parts = _parts()
    parts["backbone-node-count"] = {}
    params = app_config_from_parts(parts).params
    assert (params.min_backbone_count, params.max_backbone_count) == (3, None)


def test_app_config_from_parts_reads_only_min_when_max_absent() -> None:
    """A backbone-node-count with only ``min`` sets the floor and leaves max uncapped."""
    parts = _parts()
    parts["backbone-node-count"] = {"min": 4}
    params = app_config_from_parts(parts).params
    assert (params.min_backbone_count, params.max_backbone_count) == (4, None)


def test_app_config_from_parts_reads_backbone_placement() -> None:
    """The backbone-placement document toggles the data-center gate off."""
    parts = _parts(**{"backbone-placement": {"restrict": False}})
    assert app_config_from_parts(parts).restrict_backbone_to_datacenters is False


def test_app_config_from_parts_requires_backbone_placement() -> None:
    """A missing backbone-placement document is rejected (no default)."""
    parts = _parts()
    del parts["backbone-placement"]
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_reads_convergence_promotion() -> None:
    """The convergence-promotion document toggles the promotion pass off."""
    parts = _parts(**{"convergence-promotion": {"promote": False}})
    assert app_config_from_parts(parts).params.promote_high_degree_convergences is False


def test_app_config_from_parts_requires_convergence_promotion() -> None:
    """A missing convergence-promotion document is rejected (no default)."""
    parts = _parts()
    del parts["convergence-promotion"]
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_parses_connections() -> None:
    """Forced and prohibited connection documents are parsed into the config."""
    parts = _parts(
        **{
            "forced-connections": [{"source": "A", "target": "B", "type": "backbone-backbone"}],
            "prohibited-connections": [{"source": "C", "target": "D"}],
        }
    )
    config = app_config_from_parts(parts)
    assert (config.forced_connections, config.excluded_connections) == (
        (ForcedConnection("backbone-backbone", "A", "B"),),
        (ForcedConnection("backbone-backbone", "C", "D"),),
    )
