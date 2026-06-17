"""Load the WAN designer configuration from a YAML file.

Everything the operator tunes -- the input/output paths, the role pins and
exclusions, the core count, and the algorithm dials -- lives in one YAML file
(``etc/joint.yml`` by default) instead of being baked into the source. Any key
the file omits falls back to the matching built-in default, so a partial (even
empty) file still yields a valid configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from wan_designer.model import (
    FORCED_CONNECTION_TYPES,
    DesignPaths,
    DesignParams,
    EnumBudget,
    ForcedConnection,
    Tuning,
)

DEFAULT_CONFIG_PATH = Path("etc/joint.yml")
DEFAULT_VERTICES = {
    "AFLCMC": "data/vertices/aflcmc.csv",
    "AFNWC/NI": "data/vertices/afnwc_ni.csv",
    "AWS": [
        "data/vertices/aws_govcloud.csv",
        "data/vertices/aws_secret_east.csv",
        "data/vertices/aws_secret_west.csv",
        "data/vertices/aws_top_secret.csv",
    ],
    "Azure": "data/vertices/azure_secret.csv",
    "DCN": "data/vertices/dcn.csv",
    "F-35": "data/vertices/f_35.csv",
    "Lumen": "data/vertices/lumen.csv",
    "OCI": "data/vertices/oci.csv",
    "VisionNet": "data/vertices/vision_net.csv",
}
DEFAULT_CARRIER_EDGES = "data/edges/lumen.csv"
DEFAULT_REGIONAL_EDGES = ["data/edges/dcn.csv", "data/edges/vision_net.csv"]


@dataclass(frozen=True)
class AppConfig:
    """A fully resolved configuration: file paths, design params, augment flag."""

    paths: DesignPaths
    params: DesignParams
    resilience_augmentation: bool
    label: str = ""
    forced_connections: tuple[ForcedConnection, ...] = ()


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a named sub-mapping, defaulting to empty and rejecting non-mappings."""
    section = data.get(key, {})
    if not isinstance(section, dict):
        raise ValueError(f"config section '{key}' must be a mapping")
    return section


def _str_list(data: dict[str, Any], key: str, default: list[str]) -> tuple[str, ...]:
    """Return a list-of-strings config value as a tuple, rejecting other shapes."""
    value = data.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"config key '{key}' must be a list of strings")
    return tuple(value)


def _forced_connections(design: dict[str, Any]) -> tuple[ForcedConnection, ...]:
    """Parse the operator-pinned ``forced_connections`` edges, rejecting bad shapes.

    Each entry is a mapping with string ``source``/``target``/``type`` keys, the
    ``type`` one of :data:`FORCED_CONNECTION_TYPES`. An absent key defaults to an
    empty list (no pinned edges).
    """
    value = design.get("forced_connections", [])
    if not isinstance(value, list):
        raise ValueError("config key 'forced_connections' must be a list")
    connections: list[ForcedConnection] = []
    for item in value:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(key), str) for key in ("source", "target", "type")
        ):
            raise ValueError("each forced_connection must map source, target, and type to strings")
        if item["type"] not in FORCED_CONNECTION_TYPES:
            allowed = sorted(FORCED_CONNECTION_TYPES)
            raise ValueError(f"forced_connection type must be one of {allowed}")
        connections.append(ForcedConnection(item["type"], item["source"], item["target"]))
    return tuple(connections)


def _vertex_paths(tenant: object, value: object) -> list[tuple[str, Path]]:
    """Expand one tenant's value (a path or list of paths) into (tenant, path) pairs."""
    items = value if isinstance(value, list) else [value]
    pairs: list[tuple[str, Path]] = []
    for path in items:
        if not isinstance(tenant, str) or not isinstance(path, str):
            raise ValueError("config key 'vertices' must map tenant to a path or list of paths")
        pairs.append((tenant, Path(path)))
    return pairs


def _vertex_files(inputs: dict[str, Any]) -> tuple[tuple[str, Path], ...]:
    """Resolve the tenant -> vertices-CSV(s) mapping into sorted (tenant, path) pairs."""
    value = inputs.get("vertices", DEFAULT_VERTICES)
    if not isinstance(value, dict):
        raise ValueError("config key 'vertices' must be a mapping of tenant to path")
    pairs = [pair for tenant, paths in value.items() for pair in _vertex_paths(tenant, paths)]
    return tuple(sorted(pairs))


def _paths(inputs: dict[str, Any]) -> DesignPaths:
    """Resolve the file-path configuration into a :class:`DesignPaths`."""
    regional_edges = _str_list(inputs, "regional_edges", DEFAULT_REGIONAL_EDGES)
    off_net = inputs.get("off_net")
    return DesignPaths(
        vertex_files=_vertex_files(inputs),
        edge_path=Path(str(inputs.get("carrier_edges", DEFAULT_CARRIER_EDGES))),
        regional_edge_paths=tuple(Path(item) for item in regional_edges),
        off_net_path=Path(str(off_net)) if off_net is not None else None,
    )


def _tuning(tuning: dict[str, Any]) -> Tuning:
    """Resolve the tuning configuration into a :class:`Tuning`."""
    base = Tuning()
    return Tuning(
        cluster_min_points=tuning.get("cluster_min_points", base.cluster_min_points),
        cluster_radius_miles=(
            tuning.get("cluster_min_radius_miles", base.cluster_radius_miles[0]),
            tuning.get("cluster_max_radius_miles", base.cluster_radius_miles[1]),
        ),
        compass_octants=tuning.get("compass_octants", base.compass_octants),
        core_backbone_min_degree=tuning.get(
            "core_backbone_min_degree", base.core_backbone_min_degree
        ),
        core_coverage_target_miles=tuning.get(
            "core_coverage_target_miles", base.core_coverage_target_miles
        ),
        access_aggregation_links=tuning.get(
            "access_aggregation_links", base.access_aggregation_links
        ),
        enum_budget=EnumBudget(
            memory_fraction=tuning.get("enum_memory_fraction", base.enum_budget.memory_fraction),
            set_peak_bytes=tuning.get("core_set_peak_bytes", base.enum_budget.set_peak_bytes),
        ),
    )


def _params(design: dict[str, Any], tuning: dict[str, Any]) -> DesignParams:
    """Resolve the design and tuning configuration into :class:`DesignParams`."""
    base = DesignParams()
    return DesignParams(
        min_core_count=design.get("min_core_count", base.min_core_count),
        max_core_count=design.get("max_core_count", base.max_core_count),
        allow_roadm_aggregation=design.get(
            "allow_roadm_aggregation", base.allow_roadm_aggregation
        ),
        forced_core_names=_str_list(design, "forced_cores", []),
        forced_aggregation_names=_str_list(design, "forced_aggregations", []),
        excluded_names=_str_list(design, "excluded", []),
        tuning=_tuning(tuning),
    )


def config_from_data(data: dict[str, Any]) -> AppConfig:
    """Resolve an already-parsed config mapping into a :class:`AppConfig`."""
    design = _mapping(data, "design")
    return AppConfig(
        paths=_paths(_mapping(data, "inputs")),
        params=_params(design, _mapping(data, "tuning")),
        resilience_augmentation=design.get("resilience_augmentation", True),
        label=str(data.get("label", "")),
        forced_connections=_forced_connections(design),
    )


def default_config() -> AppConfig:
    """The built-in configuration used when no config file is supplied."""
    return config_from_data({})


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Parse the YAML config at ``path`` into a resolved :class:`AppConfig`."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    return config_from_data(raw if isinstance(raw, dict) else {})
