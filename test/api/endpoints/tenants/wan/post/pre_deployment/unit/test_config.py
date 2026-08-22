from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from synthesizer.config import AppConfig, app_config_from_parts, config_from_data
from synthesizer.model import NamedLink, OperatorLinks


_REQUIRED_TUNING = {
    "backbone_number_of_diverse_paths": 3,
    "access_backbone_links": 2,
    "backbone_coverage_target_miles": 600,
}


def _config(data: dict[str, Any]) -> AppConfig:
    merged = dict(data)
    merged["tuning"] = {**_REQUIRED_TUNING, **data.get("tuning", {})}
    synthesis = data.get("synthesis", {})
    if isinstance(synthesis, dict):
        merged["synthesis"] = {
            "promote_high_degree_convergences_to_backbone_nodes": True,
            **synthesis,
        }
    return config_from_data(merged)


def default_config() -> AppConfig:
    return _config({})


def test_default_min_backbone_count() -> None:
    assert default_config().params.min_backbone_count == 3


def test_default_has_no_forced_backbone() -> None:
    assert len(default_config().params.forced_backbone_names) == 0


def test_default_max_backbone_count_is_none() -> None:
    assert default_config().params.max_backbone_count is None


def test_default_site_files() -> None:
    lumen = ("Lumen", Path("data/pops/lumen.csv"))
    assert lumen in default_config().input_files.site_files


def test_default_regional_links() -> None:
    assert default_config().input_files.regional_link_paths == (
        Path("data/fiber_segments/terrestrial/dcn.csv"),
        Path("data/fiber_segments/terrestrial/vision_net.csv"),
    )


def test_default_off_net_path_is_none() -> None:
    assert default_config().input_files.off_net_path is None


def test_reads_off_net_path() -> None:
    assert _config({"inputs": {"off_net": "off.csv"}}).input_files.off_net_path == Path("off.csv")


def test_default_label_is_empty() -> None:
    assert default_config().label == ""


def test_reads_label() -> None:
    assert _config({"label": "Minuteman"}).label == "Minuteman"


def test_reads_min_backbone_count() -> None:
    assert _config({"synthesis": {"min_backbone_count": 5}}).params.min_backbone_count == 5


def test_reads_max_backbone_count() -> None:
    assert _config({"synthesis": {"max_backbone_count": 7}}).params.max_backbone_count == 7


def test_default_access_backbone_links() -> None:
    assert default_config().params.tuning.access_backbone_links == 2


def test_reads_access_backbone_links() -> None:
    assert _config(
        {"tuning": {"access_backbone_links": 3}}
    ).params.tuning.access_backbone_links == 3


def test_default_backbone_number_of_diverse_paths_is_three() -> None:
    assert default_config().params.tuning.backbone_number_of_diverse_paths == 3


def test_reads_backbone_number_of_diverse_paths() -> None:
    assert _config(
        {"tuning": {"backbone_number_of_diverse_paths": 4}}
    ).params.tuning.backbone_number_of_diverse_paths == 4


def test_the_old_mesh_degree_key_is_refused() -> None:
    with pytest.raises(ValueError, match="backbone_number_of_diverse_paths"):
        config_from_data({
            "synthesis": {
                    "promote_high_degree_convergences_to_backbone_nodes": True,
            },
            "tuning": {
                "backbone_mesh_degree": 3,
                "access_backbone_links": 2,
                "backbone_coverage_target_miles": 600,
            },
        })


def test_reads_forced_backbone() -> None:
    assert _config(
        {"synthesis": {"forced_backbone": ["Atlanta, GA"]}}
    ).params.forced_backbone_names == ("Atlanta, GA",)


def test_reads_degree_exempt_backbone() -> None:
    assert _config(
        {"synthesis": {"degree_exempt_backbone": ["San Jose, CA"]}}
    ).params.degree_exempt_backbone_names == ("San Jose, CA",)


def test_default_exempts_no_backbone_node_from_the_degree() -> None:
    assert len(default_config().params.degree_exempt_backbone_names) == 0


def test_degree_exempt_backbone_must_be_a_list() -> None:
    with pytest.raises(ValueError):
        _config({"synthesis": {"degree_exempt_backbone": "San Jose, CA"}})


def test_default_has_no_forced_paths() -> None:
    assert len(default_config().links.backbone) == 0


def test_reads_forced_paths() -> None:
    pinned = {"source": "Dallas, TX", "target": "Denver, CO"}
    assert _config({"synthesis": {"forced_paths": [pinned]}}).links.backbone == (
        NamedLink("Dallas, TX", "Denver, CO"),
    )


def test_forced_paths_must_be_a_list() -> None:
    with pytest.raises(ValueError):
        _config({"synthesis": {"forced_paths": {"source": "A"}}})


def test_a_forced_path_must_be_a_mapping() -> None:
    with pytest.raises(ValueError):
        _config({"synthesis": {"forced_paths": ["Dallas, TX"]}})


def test_a_forced_path_requires_a_source_and_target() -> None:
    with pytest.raises(ValueError):
        _config({"synthesis": {"forced_paths": [{"source": "A"}]}})


def test_a_forced_path_ignores_a_leftover_type() -> None:
    pinned = {"source": "A", "target": "B", "type": "access-backbone"}
    assert _config({"synthesis": {"forced_paths": [pinned]}}).links.backbone == (
        NamedLink("A", "B"),
    )


def test_default_has_no_forced_homes() -> None:
    assert len(default_config().links.access) == 0


def test_reads_forced_homes() -> None:
    home = {"source": "Kirtland, NM", "target": "Denver, CO"}
    assert _config({"synthesis": {"forced_homes": [home]}}).links.access == (
        NamedLink("Kirtland, NM", "Denver, CO"),
    )


def test_forced_homes_must_be_a_list() -> None:
    with pytest.raises(ValueError):
        _config({"synthesis": {"forced_homes": {"source": "A"}}})


def test_a_forced_home_is_not_read_as_a_mesh_pair() -> None:
    home = {"source": "Kirtland, NM", "target": "Denver, CO"}
    assert len(_config({"synthesis": {"forced_homes": [home]}}).links.backbone) == 0


def test_default_has_no_excluded_paths() -> None:
    assert len(default_config().links.removed_backbone) == 0


def test_reads_excluded_paths() -> None:
    synthesis = {"excluded_paths": [{"source": "Seattle, WA", "target": "Boise, ID"}]}
    assert _config({"synthesis": synthesis}).links.removed_backbone == (
        NamedLink("Seattle, WA", "Boise, ID"),
    )


def test_default_has_no_prohibited_backbone() -> None:
    assert len(default_config().params.exclusions.prohibited_backbone_names) == 0


def test_reads_promote_high_degree_convergences_true() -> None:
    assert _config(
        {"synthesis": {"promote_high_degree_convergences_to_backbone_nodes": True}}
    ).params.promote_high_degree_convergences is True


def test_reads_promote_high_degree_convergences_false() -> None:
    assert _config(
        {"synthesis": {"promote_high_degree_convergences_to_backbone_nodes": False}}
    ).params.promote_high_degree_convergences is False


def test_promote_high_degree_convergences_must_be_a_boolean() -> None:
    with pytest.raises(ValueError):
        _config({"synthesis": {"promote_high_degree_convergences_to_backbone_nodes": "yes"}})


def test_promote_high_degree_convergences_is_required() -> None:
    with pytest.raises(ValueError):
        config_from_data({"tuning": _REQUIRED_TUNING, "synthesis": {}})


def test_reads_prohibited_backbone() -> None:
    synthesis = {"prohibited_backbone": ["Denver, CO", "Boise, ID"]}
    assert _config({"synthesis": synthesis}).params.exclusions.prohibited_backbone_names == (
        "Denver, CO",
        "Boise, ID",
    )


def test_prohibited_backbone_must_be_a_list_of_strings() -> None:
    with pytest.raises(ValueError):
        _config({"synthesis": {"prohibited_backbone": "Denver, CO"}})


def test_reads_settings_compass_sector_count() -> None:
    tuning = _config({"settings": {"compass_sector_count": 6}}).params.tuning
    assert tuning.compass_sector_count == 6


def test_reads_tuning_coverage_target() -> None:
    assert _config(
        {"tuning": {"backbone_coverage_target_miles": 250}}
    ).params.tuning.backbone_coverage_target_miles == 250


def test_reads_settings_backbone_search_memory_share() -> None:
    assert _config(
        {"settings": {"backbone_search_memory_share": 0.3}}
    ).params.tuning.search_memory_budget.memory_share == 0.3


def test_reads_settings_bytes_per_combination() -> None:
    assert _config(
        {"settings": {"bytes_per_backbone_combination": 200}}
    ).params.tuning.search_memory_budget.bytes_per_combination == 200


@pytest.mark.parametrize("value", [0, -1, 8.0, True, "8"])
def test_rejects_a_compass_sector_count_that_is_not_a_positive_integer(
        value: object) -> None:
    with pytest.raises(ValueError, match="compass_sector_count"):
        _config({"settings": {"compass_sector_count": value}})


@pytest.mark.parametrize("value", [1.5, 0, 0.0, -0.1, True, "half"])
def test_rejects_a_memory_share_outside_zero_to_one(value: object) -> None:
    with pytest.raises(ValueError, match="backbone_search_memory_share"):
        _config({"settings": {"backbone_search_memory_share": value}})


def test_accepts_a_memory_share_of_exactly_one() -> None:
    parsed = _config({"settings": {"backbone_search_memory_share": 1}})
    budget = parsed.params.tuning.search_memory_budget
    assert budget.memory_share == 1.0


def test_rejects_a_settings_document_written_before_the_rename() -> None:
    with pytest.raises(ValueError, match="unknown keys"):
        _config({"settings": {"compass_octants": 8, "enum_memory_fraction": 0.6}})


def test_rejects_an_unrecognised_settings_key() -> None:
    with pytest.raises(ValueError, match="compass_sectors"):
        _config({"settings": {"compass_sectors": 8}})


def test_a_dial_left_in_the_tuning_section_is_not_read() -> None:
    assert _config({"tuning": {"compass_octants": 6}}).params.tuning.compass_sector_count == 8


def test_reads_sites_mapping() -> None:
    sites = {"Lumen": "lumen.csv", "F-35": "f_35.csv"}
    assert _config({"inputs": {"sites": sites}}).input_files.site_files == (
        ("F-35", Path("f_35.csv")),
        ("Lumen", Path("lumen.csv")),
    )


def test_reads_sites_list_of_paths() -> None:
    sites = {"Providers": ["region_a.csv", "region_b.csv"]}
    assert _config({"inputs": {"sites": sites}}).input_files.site_files == (
        ("Providers", Path("region_a.csv")),
        ("Providers", Path("region_b.csv")),
    )


def test_reads_carrier_fiber_segments_path() -> None:
    assert _config(
        {"inputs": {"carrier_fiber_segments": "fiber.csv"}}
    ).input_files.link_path == Path("fiber.csv")


def test_rejects_non_string_path_in_list() -> None:
    with pytest.raises(ValueError):
        _config({"inputs": {"sites": {"Providers": ["region_a.csv", 3]}}})


def test_rejects_non_mapping_sites() -> None:
    with pytest.raises(ValueError):
        _config({"inputs": {"sites": "single.csv"}})


def test_rejects_non_list_regional_links() -> None:
    with pytest.raises(ValueError):
        _config({"inputs": {"regional_links": "single.csv"}})


def test_missing_required_degree_is_rejected() -> None:
    with pytest.raises(ValueError):
        config_from_data({
            "tuning": {
                "backbone_number_of_diverse_paths": 3,
                "backbone_coverage_target_miles": 600,
            }
        })


def test_non_integer_degree_is_rejected() -> None:
    with pytest.raises(ValueError):
        config_from_data(
            {"tuning": {"backbone_number_of_diverse_paths": "three", "access_backbone_links": 2}}
        )


def test_boolean_degree_is_rejected() -> None:
    with pytest.raises(ValueError):
        config_from_data(
            {"tuning": {"backbone_number_of_diverse_paths": True, "access_backbone_links": 2}}
        )


def test_missing_coverage_target_is_rejected() -> None:
    with pytest.raises(ValueError):
        config_from_data(
            {
                "tuning": {"backbone_number_of_diverse_paths": 3, "access_backbone_links": 2},
                "synthesis": {
                    "promote_high_degree_convergences_to_backbone_nodes": True
                },
            }
        )


def test_non_number_coverage_target_is_rejected() -> None:
    with pytest.raises(ValueError):
        _config({"tuning": {"backbone_coverage_target_miles": "far"}})


def test_a_config_naming_no_backup_path_multiple_loads() -> None:
    assert config_from_data(
        {
            "tuning": {
                "backbone_number_of_diverse_paths": 3,
                "access_backbone_links": 2,
                "backbone_coverage_target_miles": 600,
            },
            "synthesis": {"promote_high_degree_convergences_to_backbone_nodes": True},
        }
    ).params.tuning.backbone_number_of_diverse_paths == 3


def test_fractional_coverage_target_is_rejected() -> None:
    with pytest.raises(ValueError):
        _config({"tuning": {"backbone_coverage_target_miles": 400.5}})


def test_section_must_be_a_mapping() -> None:
    with pytest.raises(ValueError):
        _config({"synthesis": "not a mapping"})


def test_forced_backbone_must_be_a_list() -> None:
    with pytest.raises(ValueError):
        _config({"synthesis": {"forced_backbone": "Atlanta, GA"}})


def _parts(**overrides: Any) -> dict[str, Any]:
    parts: dict[str, Any] = {
        "forced-backbone-nodes": [],
        "forced-paths": [],
        "forced-homes": [],
        "prohibited-backbone-nodes": [],
        "prohibited-paths": [],
        "backbone-node-count": {"min": 3, "max": 5},
        "backbone-number-of-diverse-paths": {"degree": 3},
        "access-homing-degree": {"degree": 2},
        "convergence-promotion": {"promote": True},
        "knobs": {"backbone_coverage_target_miles": 600},
        "label": {"label": "Minuteman"},
    }
    parts.update(overrides)
    return parts


def test_app_config_from_parts_folds_settings_into_tuning() -> None:
    parts = _parts(settings={"backbone_search_memory_share": 0.25})
    budget = app_config_from_parts(parts).params.tuning.search_memory_budget
    assert budget.memory_share == 0.25


def test_app_config_from_parts_reads_every_dial_from_settings() -> None:
    parts = _parts(settings={
        "compass_sector_count": 4, "backbone_search_memory_share": 0.25,
        "bytes_per_backbone_combination": 320,
    })
    budget = app_config_from_parts(parts).params.tuning.search_memory_budget
    assert (budget.memory_share, budget.bytes_per_combination) == (0.25, 320)


def test_app_config_from_parts_ignores_a_dial_left_in_knobs() -> None:
    parts = _parts(knobs={
        "backbone_coverage_target_miles": 600,
            "compass_octants": 4,
    })
    assert app_config_from_parts(parts).params.tuning.compass_sector_count == 8


def test_app_config_from_parts_without_settings_is_unchanged() -> None:
    assert app_config_from_parts(_parts()) == app_config_from_parts(_parts(settings={}))


def test_app_config_from_parts_assembles_the_two_degrees() -> None:
    tuning = app_config_from_parts(_parts()).params.tuning
    assert (tuning.backbone_number_of_diverse_paths, tuning.access_backbone_links) == (3, 2)


def test_app_config_from_parts_reads_the_label() -> None:
    assert app_config_from_parts(_parts()).label == "Minuteman"


def test_app_config_from_parts_reads_a_plain_label() -> None:
    assert app_config_from_parts(_parts(label="Bare")).label == "Bare"


def test_app_config_from_parts_reads_backbone_node_count() -> None:
    params = app_config_from_parts(_parts()).params
    assert (params.min_backbone_count, params.max_backbone_count) == (3, 5)


def test_app_config_from_parts_reads_forced_backbone() -> None:
    parts = _parts(**{"forced-backbone-nodes": ["Denver, CO"]})
    assert app_config_from_parts(parts).params.forced_backbone_names == ("Denver, CO",)


def test_app_config_from_parts_reads_the_degree_exempt_nodes() -> None:
    parts = _parts(**{"degree-exempt-backbone-nodes": ["San Jose, CA"]})
    exempt = app_config_from_parts(parts).params.degree_exempt_backbone_names
    assert exempt == ("San Jose, CA",)


def test_app_config_from_parts_exempts_nobody_without_the_document() -> None:
    params = app_config_from_parts(_parts()).params
    assert len(params.degree_exempt_backbone_names) == 0


def test_app_config_from_parts_requires_each_degree() -> None:
    parts = _parts()
    del parts["access-homing-degree"]
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_refuses_the_old_mesh_degree_resource() -> None:
    parts = _parts()
    parts["backbone-mesh-degree"] = parts.pop("backbone-number-of-diverse-paths")
    with pytest.raises(ValueError, match="backbone-number-of-diverse-paths"):
        app_config_from_parts(parts)


def test_app_config_from_parts_requires_coverage_target() -> None:
    parts = _parts(knobs={})
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_rejects_a_malformed_degree_document() -> None:
    parts = _parts()
    parts["backbone-number-of-diverse-paths"] = 3
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_rejects_a_non_integer_degree() -> None:
    parts = _parts()
    parts["backbone-number-of-diverse-paths"] = {"degree": "three"}
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_defaults_count_when_absent() -> None:
    parts = _parts()
    parts["backbone-node-count"] = {}
    params = app_config_from_parts(parts).params
    assert (params.min_backbone_count, params.max_backbone_count) == (3, None)


def test_app_config_from_parts_reads_only_min_when_max_absent() -> None:
    parts = _parts()
    parts["backbone-node-count"] = {"min": 4}
    params = app_config_from_parts(parts).params
    assert (params.min_backbone_count, params.max_backbone_count) == (4, None)


def test_app_config_from_parts_reads_convergence_promotion() -> None:
    parts = _parts(**{"convergence-promotion": {"promote": False}})
    assert app_config_from_parts(parts).params.promote_high_degree_convergences is False


def test_app_config_from_parts_requires_convergence_promotion() -> None:
    parts = _parts()
    del parts["convergence-promotion"]
    with pytest.raises(ValueError):
        app_config_from_parts(parts)


def test_app_config_from_parts_parses_the_written_links() -> None:
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
