from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from synthesizer.model import (
    SynthesisParams,
    InputFiles,
    NamedLink,
    OperatorLinks,
    RoleExclusions,
    SearchMemoryBudget,
    Tuning,
)

DEFAULT_SITES = {
    "DCN": "data/pops/dcn.csv",
    "F-35": "data/tenants/f_35.csv",
    "Lumen": "data/pops/lumen.csv",
    "Providers": "data/providers/providers.csv",
    "VisionNet": "data/pops/vision_net.csv",
}
DEFAULT_CARRIER_FIBER_SEGMENTS = "data/fiber_segments/terrestrial/lumen.csv"
DEFAULT_REGIONAL_LINKS = [
    "data/fiber_segments/terrestrial/dcn.csv",
    "data/fiber_segments/terrestrial/vision_net.csv",
]


@dataclass(frozen=True)
class AppConfig:
    input_files: InputFiles
    params: SynthesisParams
    label: str = ""
    links: OperatorLinks = field(default_factory=OperatorLinks)


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    section = data.get(key, {})
    if not isinstance(section, dict):
        raise ValueError(f"config section '{key}' must be a mapping")
    return section


def _str_list(data: dict[str, Any], key: str, default: list[str]) -> tuple[str, ...]:
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"config key '{key}' must be a list of strings")
    return tuple(value)


def _required_bool(data: dict[str, Any], key: str) -> bool:
    if key not in data:
        raise ValueError(f"config key '{key}' is required and has no default")
    value = data[key]
    if not isinstance(value, bool):
        raise ValueError(f"config key '{key}' must be a boolean")
    return value


def _required_int(data: dict[str, Any], key: str) -> int:
    if key not in data:
        raise ValueError(f"config key '{key}' is required and has no default")
    value = data[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"config key '{key}' must be an integer")
    return value


def _named_link_list(synthesis: dict[str, Any], key: str) -> tuple[NamedLink, ...]:
    value = synthesis.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"config key '{key}' must be a list")
    written: list[NamedLink] = []
    for item in value:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(name), str) for name in ("source", "target")
        ):
            raise ValueError(f"each {key} entry must map source and target to strings")
        written.append(NamedLink(item["source"], item["target"]))
    return tuple(written)


def _operator_links(synthesis: dict[str, Any]) -> OperatorLinks:
    return OperatorLinks(
        backbone=_named_link_list(synthesis, "forced_paths"),
        access=_named_link_list(synthesis, "forced_homes"),
        removed_backbone=_named_link_list(synthesis, "excluded_paths"),
    )


def _site_paths(tenant: object, value: object) -> list[tuple[str, Path]]:
    items = value if isinstance(value, list) else [value]
    pairs: list[tuple[str, Path]] = []
    for path in items:
        if not isinstance(tenant, str) or not isinstance(path, str):
            raise ValueError("config key 'sites' must map tenant to a path or list of paths")
        pairs.append((tenant, Path(path)))
    return pairs


def _site_files(inputs: dict[str, Any]) -> tuple[tuple[str, Path], ...]:
    value = inputs.get("sites", DEFAULT_SITES)
    if not isinstance(value, dict):
        raise ValueError("config key 'sites' must be a mapping of tenant to path")
    pairs = [pair for tenant, paths in value.items() for pair in _site_paths(tenant, paths)]
    return tuple(sorted(pairs))


def _input_files(inputs: dict[str, Any]) -> InputFiles:
    regional_links = _str_list(inputs, "regional_links", DEFAULT_REGIONAL_LINKS)
    off_net = inputs.get("off_net")
    return InputFiles(
        site_files=_site_files(inputs),
        link_path=Path(str(inputs.get("carrier_fiber_segments", DEFAULT_CARRIER_FIBER_SEGMENTS))),
        regional_link_paths=tuple(Path(item) for item in regional_links),
        off_net_path=Path(str(off_net)) if off_net is not None else None,
    )


SETTINGS_KEYS = frozenset({
    "backbone_search_memory_share",
    "bytes_per_backbone_combination",
    "compass_sector_count",
})


def _checked_settings(settings: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(settings) - SETTINGS_KEYS)
    if unknown:
        raise ValueError(
            f"settings resource carries unknown keys: {', '.join(unknown)}"
        )
    return settings


def _sector_count(settings: dict[str, Any], default: int) -> int:
    value = settings.get("compass_sector_count", default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("settings key 'compass_sector_count' must be an integer of at least 1")
    return value


def _memory_share(settings: dict[str, Any], default: float) -> float:
    value = settings.get("backbone_search_memory_share", default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("settings key 'backbone_search_memory_share' must be a number")
    if not 0.0 < value <= 1.0:
        raise ValueError(
            "settings key 'backbone_search_memory_share' must be above 0 and at most 1"
        )
    return float(value)


def _tuning(tuning: dict[str, Any], settings: dict[str, Any]) -> Tuning:
    base = Tuning()
    settings = _checked_settings(settings)
    return Tuning(
        compass_sector_count=_sector_count(settings, base.compass_sector_count),
        backbone_number_of_diverse_paths=_required_int(tuning, "backbone_number_of_diverse_paths"),
        backbone_coverage_target_miles=_required_int(
            tuning, "backbone_coverage_target_miles"
        ),
        access_backbone_links=_required_int(tuning, "access_backbone_links"),
        search_memory_budget=SearchMemoryBudget(
            memory_share=_memory_share(settings, base.search_memory_budget.memory_share),
            bytes_per_combination=settings.get(
                "bytes_per_backbone_combination", base.search_memory_budget.bytes_per_combination
            ),
        ),
    )


def _params(
    synthesis: dict[str, Any], tuning: dict[str, Any], settings: dict[str, Any]
) -> SynthesisParams:
    base = SynthesisParams()
    return SynthesisParams(
        min_backbone_count=synthesis.get("min_backbone_count", base.min_backbone_count),
        max_backbone_count=synthesis.get("max_backbone_count", base.max_backbone_count),
        forced_backbone_names=_str_list(synthesis, "forced_backbone", []),
        degree_exempt_backbone_names=_str_list(synthesis, "degree_exempt_backbone", []),
        exclusions=RoleExclusions(
            prohibited_backbone_names=_str_list(synthesis, "prohibited_backbone", []),
        ),
        tuning=_tuning(tuning, settings),
        promote_high_degree_convergences=_required_bool(
            synthesis, "promote_high_degree_convergences_to_backbone_nodes"
        ),
    )


def config_from_data(data: dict[str, Any]) -> AppConfig:
    synthesis = _mapping(data, "synthesis")
    return AppConfig(
        input_files=_input_files(_mapping(data, "inputs")),
        params=_params(synthesis, _mapping(data, "tuning"), _mapping(data, "settings")),
        label=str(data.get("label", "")),
        links=_operator_links(synthesis),
    )


def _degree(parts: dict[str, Any], resource: str) -> int:
    if resource not in parts:
        raise ValueError(f"required tenant resource '{resource}' is missing")
    doc = parts[resource]
    if not isinstance(doc, dict) or "degree" not in doc:
        raise ValueError(f"resource '{resource}' must be an object with a 'degree' integer")
    value = doc["degree"]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"resource '{resource}' degree must be an integer")
    return value


def app_config_from_parts(parts: dict[str, Any]) -> AppConfig:
    count = _mapping(parts, "backbone-node-count")
    synthesis: dict[str, Any] = {
        "forced_backbone": parts.get("forced-backbone-nodes", []),
        "degree_exempt_backbone": parts.get("degree-exempt-backbone-nodes", []),
        "prohibited_backbone": parts.get("prohibited-backbone-nodes", []),
        "forced_paths": parts.get("forced-paths", []),
        "forced_homes": parts.get("forced-homes", []),
        "excluded_paths": parts.get("prohibited-paths", []),
    }
    promotion = _mapping(parts, "convergence-promotion")
    if "promote" in promotion:
        synthesis["promote_high_degree_convergences_to_backbone_nodes"] = promotion["promote"]
    if "min" in count:
        synthesis["min_backbone_count"] = count["min"]
    if "max" in count:
        synthesis["max_backbone_count"] = count["max"]
    tuning = {
        **_mapping(parts, "knobs"),
        "backbone_number_of_diverse_paths": _degree(parts, "backbone-number-of-diverse-paths"),
        "access_backbone_links": _degree(parts, "access-homing-degree"),
    }
    label = parts.get("label", {})
    label_text = label.get("label", "") if isinstance(label, dict) else str(label)
    return config_from_data({
        "synthesis": synthesis,
        "tuning": tuning,
        "settings": _mapping(parts, "settings"),
        "label": label_text,
    })
