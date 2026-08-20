"""Unit tests for resolving the WAN synthesizer configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from synthesizer.config import AppConfig, app_config_from_parts, config_from_data
from synthesizer.model import NamedLink, OperatorLinks


# The two redundancy degrees, the coverage target and the backup path multiple are
# required (no default); inject them so each test can focus on the field under test
# without restating them.
_REQUIRED_TUNING = {
    "backbone_number_of_diverse_paths": 3,
    "access_backbone_links": 2,
    "backbone_coverage_target_miles": 600,
    "backbone_max_backup_path_multiple": 3,
}


def _config(data: dict[str, Any]) -> AppConfig:
    """Resolve a single in-memory config mapping (with required fields) for one test.

    ``restrict_backbone_to_data_centers`` (like the two redundancy degrees) is required
    with no default, so it is injected into the synthesis section unless the test overrides
    it -- letting each test focus on the field under test. A non-mapping ``synthesis`` is
    passed through so the "section must be a mapping" rejection still fires.
    """
    merged = dict(data)
    merged["tuning"] = {**_REQUIRED_TUNING, **data.get("tuning", {})}
    synthesis = data.get("synthesis", {})
    if isinstance(synthesis, dict):
        merged["synthesis"] = {
            "restrict_backbone_to_data_centers": True,
            "promote_high_degree_convergences_to_backbone_nodes": True,
            **synthesis,
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
    lumen = ("Lumen", Path("data/pops/lumen.csv"))
    assert lumen in default_config().input_files.vertex_files


def test_default_regional_edges() -> None:
    """The default config lists both regional carrier edge files."""
    assert default_config().input_files.regional_edge_paths == (
        Path("data/fiber_segments/dcn.csv"),
        Path("data/fiber_segments/vision_net.csv"),
    )


def test_default_off_net_path_is_none() -> None:
    """The default config configures no off-net site file."""
    assert default_config().input_files.off_net_path is None


def test_reads_off_net_path() -> None:
    """An inputs.off_net value is read into the input files."""
    assert _config({"inputs": {"off_net": "off.csv"}}).input_files.off_net_path == Path("off.csv")


def test_default_label_is_empty() -> None:
    """The default config carries no display label."""
    assert default_config().label == ""


def test_reads_label() -> None:
    """A top-level label is read into the config for the API to surface."""
    assert _config({"label": "Minuteman"}).label == "Minuteman"


def test_reads_min_backbone_count() -> None:
    """A min_backbone_count value is read from the synthesis section."""
    assert _config({"synthesis": {"min_backbone_count": 5}}).params.min_backbone_count == 5


def test_reads_max_backbone_count() -> None:
    """A max_backbone_count value is read from the synthesis section."""
    assert _config({"synthesis": {"max_backbone_count": 7}}).params.max_backbone_count == 7


def test_default_access_backbone_links() -> None:
    """The default config homes each demand vertex to two backbone nodes."""
    assert default_config().params.tuning.access_backbone_links == 2


def test_reads_access_backbone_links() -> None:
    """An access_backbone_links value is read from the tuning section."""
    assert _config(
        {"tuning": {"access_backbone_links": 3}}
    ).params.tuning.access_backbone_links == 3


def test_default_backbone_number_of_diverse_paths_is_three() -> None:
    """The default config wires each backbone node to three others on the mesh."""
    assert default_config().params.tuning.backbone_number_of_diverse_paths == 3


def test_reads_backbone_number_of_diverse_paths() -> None:
    """A backbone_number_of_diverse_paths value is read into the tuning."""
    assert _config(
        {"tuning": {"backbone_number_of_diverse_paths": 4}}
    ).params.tuning.backbone_number_of_diverse_paths == 4


def test_the_old_mesh_degree_key_is_refused() -> None:
    """A tuning document still calling the setting a mesh degree is refused by name.

    The key was renamed rather than aliased, so a tenant config written before the rename
    does not quietly fall through to a construction fallback nobody chose. It fails, and
    the message names the key that was wanted.
    """
    with pytest.raises(ValueError, match="backbone_number_of_diverse_paths"):
        config_from_data({
            "synthesis": {
                "restrict_backbone_to_data_centers": True,
                "promote_high_degree_convergences_to_backbone_nodes": True,
            },
            "tuning": {
                "backbone_mesh_degree": 3,
                "access_backbone_links": 2,
                "backbone_coverage_target_miles": 600,
            },
        })


def test_reads_forced_backbone() -> None:
    """A forced_backbone list is read into the synthesis params."""
    assert _config(
        {"synthesis": {"forced_backbone": ["Atlanta, GA"]}}
    ).params.forced_backbone_names == ("Atlanta, GA",)


def test_reads_degree_exempt_backbone() -> None:
    """A degree_exempt_backbone list is read into the synthesis params."""
    assert _config(
        {"synthesis": {"degree_exempt_backbone": ["San Jose, CA"]}}
    ).params.degree_exempt_backbone_names == ("San Jose, CA",)


def test_default_exempts_no_backbone_node_from_the_degree() -> None:
    """The default config holds every backbone node to the diverse path count."""
    assert len(default_config().params.degree_exempt_backbone_names) == 0


def test_degree_exempt_backbone_must_be_a_list() -> None:
    """A non-list degree_exempt_backbone value is rejected."""
    with pytest.raises(ValueError):
        _config({"synthesis": {"degree_exempt_backbone": "San Jose, CA"}})


def test_default_has_no_forced_paths() -> None:
    """The default config pins no mesh pairs."""
    assert len(default_config().links.backbone) == 0


def test_reads_forced_paths() -> None:
    """A forced_paths list is parsed into the backbone list of written links."""
    pinned = {"source": "Dallas, TX", "target": "Denver, CO"}
    assert _config({"synthesis": {"forced_paths": [pinned]}}).links.backbone == (
        NamedLink("Dallas, TX", "Denver, CO"),
    )


def test_forced_paths_must_be_a_list() -> None:
    """A non-list forced_paths value is rejected."""
    with pytest.raises(ValueError):
        _config({"synthesis": {"forced_paths": {"source": "A"}}})


def test_a_forced_path_must_be_a_mapping() -> None:
    """A forced_paths entry that is not a mapping is rejected."""
    with pytest.raises(ValueError):
        _config({"synthesis": {"forced_paths": ["Dallas, TX"]}})


def test_a_forced_path_requires_a_source_and_target() -> None:
    """A forced_paths entry missing an endpoint is rejected."""
    with pytest.raises(ValueError):
        _config({"synthesis": {"forced_paths": [{"source": "A"}]}})


def test_a_forced_path_ignores_a_leftover_type() -> None:
    """A `type` still present on a stored entry is read past rather than refused.

    Tolerating it is what makes the split deployable. The stored documents and the Lambda
    that reads them are updated by two independent workflows, so between the new Lambda
    deploying and the next seed run the store still holds entries a previous run wrote
    with a `type`. Refusing the key -- as the settings resource refuses one it does not
    define -- would fail every WAN build in that window.
    """
    pinned = {"source": "A", "target": "B", "type": "access-backbone"}
    assert _config({"synthesis": {"forced_paths": [pinned]}}).links.backbone == (
        NamedLink("A", "B"),
    )


def test_default_has_no_forced_homes() -> None:
    """The default config pins no homes."""
    assert len(default_config().links.access) == 0


def test_reads_forced_homes() -> None:
    """A forced_homes list is parsed into the access list of written links.

    No tenant writes one today, so this is the only thing holding the path up: an access
    site pinned onto a named backbone node has to parse before it can reach the synthesis.
    """
    home = {"source": "Kirtland, NM", "target": "Denver, CO"}
    assert _config({"synthesis": {"forced_homes": [home]}}).links.access == (
        NamedLink("Kirtland, NM", "Denver, CO"),
    )


def test_forced_homes_must_be_a_list() -> None:
    """A non-list forced_homes value is rejected."""
    with pytest.raises(ValueError):
        _config({"synthesis": {"forced_homes": {"source": "A"}}})


def test_a_forced_home_is_not_read_as_a_mesh_pair() -> None:
    """A forced_homes entry never lands among the pinned mesh pairs."""
    home = {"source": "Kirtland, NM", "target": "Denver, CO"}
    assert len(_config({"synthesis": {"forced_homes": [home]}}).links.backbone) == 0


def test_default_has_no_excluded_paths() -> None:
    """The default config prunes no mesh pairs."""
    assert len(default_config().links.removed_backbone) == 0


def test_reads_excluded_paths() -> None:
    """An excluded_paths entry is parsed into the pruned list of written links."""
    synthesis = {"excluded_paths": [{"source": "Seattle, WA", "target": "Boise, ID"}]}
    assert _config({"synthesis": synthesis}).links.removed_backbone == (
        NamedLink("Seattle, WA", "Boise, ID"),
    )


def test_default_has_no_prohibited_backbone() -> None:
    """The default config bars no PoP from the backbone."""
    assert len(default_config().params.exclusions.prohibited_backbone_names) == 0


def test_reads_restrict_backbone_to_data_centers_true() -> None:
    """A restrict_backbone_to_data_centers=true synthesis gates the backbone to data centers."""
    assert _config(
        {"synthesis": {"restrict_backbone_to_data_centers": True}}
    ).restrict_backbone_to_datacenters is True


def test_reads_restrict_backbone_to_data_centers_false() -> None:
    """A restrict_backbone_to_data_centers=false synthesis opens the backbone to any city."""
    assert _config(
        {"synthesis": {"restrict_backbone_to_data_centers": False}}
    ).restrict_backbone_to_datacenters is False


def test_restrict_backbone_to_data_centers_must_be_a_boolean() -> None:
    """A non-boolean restrict_backbone_to_data_centers value is rejected."""
    with pytest.raises(ValueError):
        _config({"synthesis": {"restrict_backbone_to_data_centers": "yes"}})


def test_restrict_backbone_to_data_centers_is_required() -> None:
    """A synthesis omitting restrict_backbone_to_data_centers is rejected (no default)."""
    with pytest.raises(ValueError):
        config_from_data({"tuning": _REQUIRED_TUNING})


def test_reads_promote_high_degree_convergences_true() -> None:
    """A promote...=true synthesis lets the convergence pass seat high-degree hubs."""
    assert _config(
        {"synthesis": {"promote_high_degree_convergences_to_backbone_nodes": True}}
    ).params.promote_high_degree_convergences is True


def test_reads_promote_high_degree_convergences_false() -> None:
    """A promote...=false synthesis turns the convergence promotion pass off."""
    assert _config(
        {"synthesis": {"promote_high_degree_convergences_to_backbone_nodes": False}}
    ).params.promote_high_degree_convergences is False


def test_promote_high_degree_convergences_must_be_a_boolean() -> None:
    """A non-boolean promote_high_degree_convergences_to_backbone_nodes value is rejected."""
    with pytest.raises(ValueError):
        _config({"synthesis": {"promote_high_degree_convergences_to_backbone_nodes": "yes"}})


def test_promote_high_degree_convergences_is_required() -> None:
    """A synthesis omitting promote_high_degree_convergences_to_backbone_nodes is rejected."""
    with pytest.raises(ValueError):
        config_from_data(
            {
                "tuning": _REQUIRED_TUNING,
                "synthesis": {"restrict_backbone_to_data_centers": True},
            }
        )


def test_reads_prohibited_backbone() -> None:
    """A prohibited_backbone list is read into the synthesis params."""
    synthesis = {"prohibited_backbone": ["Denver, CO", "Boise, ID"]}
    assert _config({"synthesis": synthesis}).params.exclusions.prohibited_backbone_names == (
        "Denver, CO",
        "Boise, ID",
    )


def test_prohibited_backbone_must_be_a_list_of_strings() -> None:
    """A prohibited_backbone value that is not a list of strings is rejected."""
    with pytest.raises(ValueError):
        _config({"synthesis": {"prohibited_backbone": "Denver, CO"}})


def test_reads_settings_compass_sector_count() -> None:
    """A settings compass_sector_count value is read into the synthesis params."""
    tuning = _config({"settings": {"compass_sector_count": 6}}).params.tuning
    assert tuning.compass_sector_count == 6


def test_reads_tuning_coverage_target() -> None:
    """A tuning backbone_coverage_target_miles value is read into the synthesis params."""
    assert _config(
        {"tuning": {"backbone_coverage_target_miles": 250}}
    ).params.tuning.backbone_coverage_target_miles == 250


def test_reads_settings_backbone_search_memory_share() -> None:
    """A settings memory-share value is read into the enumeration budget."""
    assert _config(
        {"settings": {"backbone_search_memory_share": 0.3}}
    ).params.tuning.search_memory_budget.memory_share == 0.3


def test_reads_settings_bytes_per_combination() -> None:
    """A settings per-combination byte cost is read into the enumeration budget."""
    assert _config(
        {"settings": {"bytes_per_backbone_combination": 200}}
    ).params.tuning.search_memory_budget.bytes_per_combination == 200


@pytest.mark.parametrize("value", [0, -1, 8.0, True, "8"])
def test_rejects_a_compass_sector_count_that_is_not_a_positive_integer(
        value: object) -> None:
    """A sector count below one, or not an integer, is refused when the config parses."""
    with pytest.raises(ValueError, match="compass_sector_count"):
        _config({"settings": {"compass_sector_count": value}})


@pytest.mark.parametrize("value", [1.5, 0, 0.0, -0.1, True, "half"])
def test_rejects_a_memory_share_outside_zero_to_one(value: object) -> None:
    """A memory share not above 0 and at most 1 is refused when the config parses."""
    with pytest.raises(ValueError, match="backbone_search_memory_share"):
        _config({"settings": {"backbone_search_memory_share": value}})


def test_accepts_a_memory_share_of_exactly_one() -> None:
    """A memory share of exactly 1 -- all the memory the function has -- is accepted."""
    parsed = _config({"settings": {"backbone_search_memory_share": 1}})
    budget = parsed.params.tuning.search_memory_budget
    assert budget.memory_share == 1.0


def test_rejects_a_settings_document_written_before_the_rename() -> None:
    """A stored document carrying only the old key names is refused, not defaulted."""
    with pytest.raises(ValueError, match="unknown keys"):
        _config({"settings": {"compass_octants": 8, "enum_memory_fraction": 0.6}})


def test_rejects_an_unrecognised_settings_key() -> None:
    """A key the settings resource does not define is refused when the config parses."""
    with pytest.raises(ValueError, match="compass_sectors"):
        _config({"settings": {"compass_sectors": 8}})


def test_a_dial_left_in_the_tuning_section_is_not_read() -> None:
    """A dial left in the tuning section is ignored, so the built-in default stands."""
    assert _config({"tuning": {"compass_octants": 6}}).params.tuning.compass_sector_count == 8


def test_reads_vertices_mapping() -> None:
    """A vertices tenant->path mapping is read into sorted (tenant, path) pairs."""
    vertices = {"Lumen": "lumen.csv", "F-35": "f_35.csv"}
    assert _config({"inputs": {"vertices": vertices}}).input_files.vertex_files == (
        ("F-35", Path("f_35.csv")),
        ("Lumen", Path("lumen.csv")),
    )


def test_reads_vertices_list_of_paths() -> None:
    """A tenant mapped to a list expands into one (tenant, path) pair per entry."""
    vertices = {"Providers": ["region_a.csv", "region_b.csv"]}
    assert _config({"inputs": {"vertices": vertices}}).input_files.vertex_files == (
        ("Providers", Path("region_a.csv")),
        ("Providers", Path("region_b.csv")),
    )


def test_reads_carrier_edges_path() -> None:
    """An inputs.carrier_edges value is read into the input files."""
    assert _config(
        {"inputs": {"carrier_edges": "fiber.csv"}}
    ).input_files.edge_path == Path("fiber.csv")


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
        config_from_data({
            "tuning": {
                "backbone_number_of_diverse_paths": 3,
                "backbone_coverage_target_miles": 600,
            }
        })


def test_non_integer_degree_is_rejected() -> None:
    """A required degree that is not an integer is rejected."""
    with pytest.raises(ValueError):
        config_from_data(
            {"tuning": {"backbone_number_of_diverse_paths": "three", "access_backbone_links": 2}}
        )


def test_boolean_degree_is_rejected() -> None:
    """A required degree given as a bool (an int subclass) is rejected."""
    with pytest.raises(ValueError):
        config_from_data(
            {"tuning": {"backbone_number_of_diverse_paths": True, "access_backbone_links": 2}}
        )


def test_missing_coverage_target_is_rejected() -> None:
    """A config whose tuning omits the required coverage target is rejected."""
    with pytest.raises(ValueError):
        config_from_data(
            {
                "tuning": {"backbone_number_of_diverse_paths": 3, "access_backbone_links": 2},
                "synthesis": {"restrict_backbone_to_data_centers": True},
            }
        )


def test_non_number_coverage_target_is_rejected() -> None:
    """A coverage target that is not a number is rejected."""
    with pytest.raises(ValueError):
        _config({"tuning": {"backbone_coverage_target_miles": "far"}})


def test_reads_tuning_max_backup_path_multiple() -> None:
    """A tuning backbone_max_backup_path_multiple value is read into the synthesis params."""
    assert _config(
        {"tuning": {"backbone_max_backup_path_multiple": 4}}
    ).params.tuning.backbone_max_backup_path_multiple == 4.0


def test_missing_max_backup_path_multiple_is_rejected() -> None:
    """A config whose tuning omits the required backup path multiple is rejected."""
    with pytest.raises(ValueError):
        config_from_data(
            {
                "tuning": {
                    "backbone_number_of_diverse_paths": 3,
                    "access_backbone_links": 2,
                    "backbone_coverage_target_miles": 600,
                },
                "synthesis": {"restrict_backbone_to_data_centers": True},
            }
        )


def test_non_number_max_backup_path_multiple_is_rejected() -> None:
    """A backup path multiple that is not a number is rejected."""
    with pytest.raises(ValueError):
        _config({"tuning": {"backbone_max_backup_path_multiple": "three times"}})


def test_boolean_max_backup_path_multiple_is_rejected() -> None:
    """A backup path multiple given as a bool (an int subclass) is rejected."""
    with pytest.raises(ValueError):
        _config({"tuning": {"backbone_max_backup_path_multiple": True}})


def test_max_backup_path_multiple_of_one_is_rejected() -> None:
    """A bound of exactly one is rejected: it admits only the shortest path.

    A protect path takes a detour by definition, so a bound that leaves no room for one
    would refuse every synthesis rather than bounding it, and an operator who wrote it has
    almost certainly not meant to forbid path diversity outright.
    """
    with pytest.raises(ValueError):
        _config({"tuning": {"backbone_max_backup_path_multiple": 1}})


def test_fractional_max_backup_path_multiple_is_accepted() -> None:
    """A fractional bound is kept: a ratio has resolution a whole-mile target does not."""
    assert _config(
        {"tuning": {"backbone_max_backup_path_multiple": 2.5}}
    ).params.tuning.backbone_max_backup_path_multiple == 2.5


def test_fractional_coverage_target_is_rejected() -> None:
    """A coverage target carrying a fraction of a mile is rejected.

    The target is compared against a great-circle haul standing in for a last-mile
    build, so the synthesis has no sub-mile resolution for a fraction to mean anything
    in; a decimal point states a precision that is not there.
    """
    with pytest.raises(ValueError):
        _config({"tuning": {"backbone_coverage_target_miles": 400.5}})


def test_section_must_be_a_mapping() -> None:
    """A non-mapping section is rejected."""
    with pytest.raises(ValueError):
        _config({"synthesis": "not a mapping"})


def test_forced_backbone_must_be_a_list() -> None:
    """A non-list forced_backbone value is rejected."""
    with pytest.raises(ValueError):
        _config({"synthesis": {"forced_backbone": "Atlanta, GA"}})


def _parts(**overrides: Any) -> dict[str, Any]:
    """A full set of per-resource tenant documents for the assembler."""
    parts: dict[str, Any] = {
        "forced-backbone-nodes": [],
        "forced-paths": [],
        "forced-homes": [],
        "prohibited-backbone-nodes": [],
        "prohibited-paths": [],
        "backbone-node-count": {"min": 3, "max": 5},
        "backbone-number-of-diverse-paths": {"degree": 3},
        "access-homing-degree": {"degree": 2},
        "backbone-placement": {"restrict": True},
        "convergence-promotion": {"promote": True},
        "knobs": {"backbone_coverage_target_miles": 600, "backbone_max_backup_path_multiple": 3},
        "label": {"label": "Minuteman"},
    }
    parts.update(overrides)
    return parts


def test_app_config_from_parts_folds_settings_into_tuning() -> None:
    """A settings document supplies tuning values alongside the knobs document."""
    parts = _parts(settings={"backbone_search_memory_share": 0.25})
    budget = app_config_from_parts(parts).params.tuning.search_memory_budget
    assert budget.memory_share == 0.25


def test_app_config_from_parts_reads_every_dial_from_settings() -> None:
    """The three implementation dials come from the settings document."""
    parts = _parts(settings={
        "compass_sector_count": 4, "backbone_search_memory_share": 0.25,
        "bytes_per_backbone_combination": 320,
    })
    budget = app_config_from_parts(parts).params.tuning.search_memory_budget
    assert (budget.memory_share, budget.bytes_per_combination) == (0.25, 320)


def test_app_config_from_parts_ignores_a_dial_left_in_knobs() -> None:
    """A dial an operator left behind under knobs no longer steers the search."""
    parts = _parts(knobs={
        "backbone_coverage_target_miles": 600,
        "backbone_max_backup_path_multiple": 3,
        "compass_octants": 4,
    })
    assert app_config_from_parts(parts).params.tuning.compass_sector_count == 8


def test_app_config_from_parts_without_settings_is_unchanged() -> None:
    """A tenant carrying no settings document parses exactly as it did before."""
    assert app_config_from_parts(_parts()) == app_config_from_parts(_parts(settings={}))


def test_app_config_from_parts_assembles_the_two_degrees() -> None:
    """The assembler reads both redundancy degrees from their documents."""
    tuning = app_config_from_parts(_parts()).params.tuning
    assert (tuning.backbone_number_of_diverse_paths, tuning.access_backbone_links) == (3, 2)


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


def test_app_config_from_parts_reads_the_degree_exempt_nodes() -> None:
    """The assembler reads the degree-exempt-backbone-nodes document into the params."""
    parts = _parts(**{"degree-exempt-backbone-nodes": ["San Jose, CA"]})
    exempt = app_config_from_parts(parts).params.degree_exempt_backbone_names
    assert exempt == ("San Jose, CA",)


def test_app_config_from_parts_exempts_nobody_without_the_document() -> None:
    """A tenant carrying no exemption document holds every node to the diverse path count."""
    params = app_config_from_parts(_parts()).params
    assert len(params.degree_exempt_backbone_names) == 0


def test_app_config_from_parts_requires_each_degree() -> None:
    """A missing degree document is rejected by the assembler."""
    parts = _parts()
    del parts["access-homing-degree"]
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_refuses_the_old_mesh_degree_resource() -> None:
    """A tenant still storing the setting under its old resource name is refused.

    The stored resource was renamed with the config key, and neither name is an alias for
    the other, so a store the seed tool has not been run against since the rename reads as
    a tenant that never stated the number -- which is a refusal, not a default.
    """
    parts = _parts()
    parts["backbone-mesh-degree"] = parts.pop("backbone-number-of-diverse-paths")
    with pytest.raises(ValueError, match="backbone-number-of-diverse-paths"):
        app_config_from_parts(parts)


def test_app_config_from_parts_requires_coverage_target() -> None:
    """A knobs document omitting the coverage target is rejected by the assembler."""
    parts = _parts(knobs={"backbone_max_backup_path_multiple": 3})
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_requires_max_backup_path_multiple() -> None:
    """A knobs document omitting the backup path multiple is rejected by the assembler."""
    parts = _parts(knobs={"backbone_coverage_target_miles": 600})
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_rejects_a_malformed_degree_document() -> None:
    """A degree document that is not a ``{"degree": int}`` object is rejected."""
    parts = _parts()
    parts["backbone-number-of-diverse-paths"] = 3
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_rejects_a_non_integer_degree() -> None:
    """A degree document whose value is not an integer is rejected."""
    parts = _parts()
    parts["backbone-number-of-diverse-paths"] = {"degree": "three"}
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


def test_app_config_from_parts_parses_the_written_links() -> None:
    """The three link documents are parsed into the three lists of written links.

    Each stored document lands in its own list and only its own, which is the whole point
    of the split: the tier is the document a link was written in, and `forced-homes` is
    carried here end to end even though no tenant populates it.
    """
    parts = _parts(
        **{
            "forced-paths": [{"source": "A", "target": "B"}],
            "forced-homes": [{"source": "S", "target": "B"}],
            "prohibited-paths": [{"source": "C", "target": "D"}],
        }
    )
    assert app_config_from_parts(parts).links == OperatorLinks(
        backbone=(NamedLink("A", "B"),),
        access=(NamedLink("S", "B"),),
        removed_backbone=(NamedLink("C", "D"),),
    )
