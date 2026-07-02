"""Resolve the WAN designer configuration from an already-parsed mapping.

Everything the operator tunes -- the input paths, the role pins and exclusions,
the backbone count, and the algorithm dials -- arrives as one parsed mapping (the
tenant's stored config JSON). Any key it omits falls back to the matching
built-in default, so a partial (even empty) mapping still yields a valid
configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from synthesizer.model import (
    FORCED_CONNECTION_TYPES,
    DesignPaths,
    DesignParams,
    EnumBudget,
    ForcedConnection,
    RoleExclusions,
    Tuning,
)

DEFAULT_VERTICES = {
    "AFLCMC": "data/vertices/tenants/aflcmc.csv",
    "AFNWC/NI": "data/vertices/tenants/afnwc_ni.csv",
    "AWS": [
        "data/vertices/csps/aws/aws_govcloud.csv",
        "data/vertices/csps/aws/aws_secret_east.csv",
        "data/vertices/csps/aws/aws_secret_west.csv",
        "data/vertices/csps/aws/aws_top_secret_east.csv",
        "data/vertices/csps/aws/aws_top_secret_west.csv",
    ],
    "Azure": [
        "data/vertices/csps/azure/azure_secret_east.csv",
        "data/vertices/csps/azure/azure_secret_west.csv",
    ],
    "DCN": "data/vertices/carriers/dcn.csv",
    "F-35": "data/vertices/tenants/f_35.csv",
    "Lumen": "data/vertices/carriers/lumen.csv",
    "OCI": [
        "data/vertices/csps/oci/oci_east.csv",
        "data/vertices/csps/oci/oci_west.csv",
    ],
    "VisionNet": "data/vertices/carriers/vision_net.csv",
}
DEFAULT_CARRIER_EDGES = "data/edges/lumen.csv"
DEFAULT_REGIONAL_EDGES = ["data/edges/dcn.csv", "data/edges/vision_net.csv"]


@dataclass(frozen=True)
class AppConfig:
    """A fully resolved configuration: file paths, design params, pinned edges."""

    paths: DesignPaths
    params: DesignParams
    label: str = ""
    forced_connections: tuple[ForcedConnection, ...] = ()
    excluded_connections: tuple[ForcedConnection, ...] = ()


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


def _bool(data: dict[str, Any], key: str, default: bool) -> bool:
    """Return a boolean config value, defaulting when absent and rejecting non-bools."""
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"config key '{key}' must be a boolean")
    return value


def _required_int(data: dict[str, Any], key: str) -> int:
    """Return a required integer config value, rejecting an absent or non-int value.

    The two redundancy degrees (``backbone-mesh-degree``, ``access-homing-degree``)
    have no default: every tenant must state each one, so a missing key is an error
    rather than a silently-filled fallback.
    """
    if key not in data:
        raise ValueError(f"config key '{key}' is required and has no default")
    value = data[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"config key '{key}' must be an integer")
    return value


def _connection_list(
    design: dict[str, Any],
    key: str,
    allowed_types: frozenset[str],
    default_type: str | None,
) -> tuple[ForcedConnection, ...]:
    """Parse a list of operator connection mappings, rejecting bad shapes.

    Each entry maps string ``source``/``target`` plus a ``type`` in
    ``allowed_types``. ``default_type`` fills an absent ``type`` (use ``None`` to
    require it); an absent ``key`` defaults to an empty list (no connections).
    """
    value = design.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"config key '{key}' must be a list")
    connections: list[ForcedConnection] = []
    for item in value:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(field), str) for field in ("source", "target")
        ):
            raise ValueError(f"each {key} entry must map source and target to strings")
        edge_type = item.get("type", default_type)
        if edge_type not in allowed_types:
            raise ValueError(f"{key} type must be one of {sorted(allowed_types)}")
        connections.append(ForcedConnection(edge_type, item["source"], item["target"]))
    return tuple(connections)


def _forced_connections(design: dict[str, Any]) -> tuple[ForcedConnection, ...]:
    """Parse the operator-pinned ``forced_connections`` edges (``type`` required)."""
    return _connection_list(design, "forced_connections", FORCED_CONNECTION_TYPES, None)


def _excluded_connections(design: dict[str, Any]) -> tuple[ForcedConnection, ...]:
    """Parse the operator-pruned ``excluded_connections`` (``backbone-backbone`` only).

    The only mesh link an operator may remove is a ``backbone-backbone`` pair, so
    ``type`` defaults to and must be ``backbone-backbone``.
    """
    return _connection_list(
        design, "excluded_connections", frozenset({"backbone-backbone"}), "backbone-backbone"
    )


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
        compass_octants=tuning.get("compass_octants", base.compass_octants),
        backbone_mesh_degree=_required_int(tuning, "backbone_mesh_degree"),
        backbone_coverage_target_miles=tuning.get(
            "backbone_coverage_target_miles", base.backbone_coverage_target_miles
        ),
        access_backbone_links=_required_int(tuning, "access_backbone_links"),
        enum_budget=EnumBudget(
            memory_fraction=tuning.get("enum_memory_fraction", base.enum_budget.memory_fraction),
            set_peak_bytes=tuning.get("backbone_set_peak_bytes", base.enum_budget.set_peak_bytes),
        ),
    )


def _params(design: dict[str, Any], tuning: dict[str, Any]) -> DesignParams:
    """Resolve the design and tuning configuration into :class:`DesignParams`."""
    base = DesignParams()
    return DesignParams(
        min_backbone_count=design.get("min_backbone_count", base.min_backbone_count),
        max_backbone_count=design.get("max_backbone_count", base.max_backbone_count),
        forced_backbone_names=_str_list(design, "forced_backbone", []),
        exclusions=RoleExclusions(
            prohibited_backbone_names=_str_list(design, "prohibited_backbone", []),
        ),
        restrict_backbone_to_datacenters=_bool(
            design,
            "restrict_backbone_to_data_centers",
            base.restrict_backbone_to_datacenters,
        ),
        tuning=_tuning(tuning),
    )


def config_from_data(data: dict[str, Any]) -> AppConfig:
    """Resolve an already-parsed config mapping into a :class:`AppConfig`.

    Any key the mapping omits falls back to the matching built-in default, so a
    partial (even empty) mapping still yields a valid configuration. ``datacenter_cities``
    is threaded by the worker handler, not parsed from these documents.
    """
    design = _mapping(data, "design")
    return AppConfig(
        paths=_paths(_mapping(data, "inputs")),
        params=_params(design, _mapping(data, "tuning")),
        label=str(data.get("label", "")),
        forced_connections=_forced_connections(design),
        excluded_connections=_excluded_connections(design),
    )


def _degree(parts: dict[str, Any], resource: str) -> int:
    """Read a required ``{"degree": int}`` document for a redundancy resource."""
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
    """Assemble an :class:`AppConfig` from the per-resource tenant documents.

    Each operator concern is its own stored document (``forced-backbone-nodes``,
    ``prohibited-connections``, ``backbone-mesh-degree``, ``knobs``, ...). This
    reshapes those documents into the canonical mapping :func:`config_from_data`
    expects and delegates to it, so all parsing and validation stays in one place. The
    two redundancy degrees are required -- a missing one raises in :func:`_degree`.
    ``paths`` is left at its defaults: the deployed synthesizer reads its substrate
    from the merged carriers, not from these documents.
    """
    count = _mapping(parts, "backbone-node-count")
    design: dict[str, Any] = {
        "forced_backbone": parts.get("forced-backbone-nodes", []),
        "prohibited_backbone": parts.get("prohibited-backbone-nodes", []),
        "forced_connections": parts.get("forced-connections", []),
        "excluded_connections": parts.get("prohibited-connections", []),
        "restrict_backbone_to_data_centers": _mapping(
            parts, "backbone-placement"
        ).get("restrict", True),
    }
    if "min" in count:
        design["min_backbone_count"] = count["min"]
    if "max" in count:
        design["max_backbone_count"] = count["max"]
    tuning = {
        **_mapping(parts, "knobs"),
        "backbone_mesh_degree": _degree(parts, "backbone-mesh-degree"),
        "access_backbone_links": _degree(parts, "access-homing-degree"),
    }
    label = parts.get("label", {})
    label_text = label.get("label", "") if isinstance(label, dict) else str(label)
    return config_from_data({"design": design, "tuning": tuning, "label": label_text})
