"""Resolve the WAN designer configuration from an already-parsed mapping.

Everything the operator tunes -- the input paths, the role pins and exclusions,
the backbone count, and the algorithm dials -- arrives as one parsed mapping (the
tenant's stored config JSON). Any key it omits falls back to the matching
built-in default, so a partial (even empty) mapping still yields a valid
configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from synthesizer.model import (
    DesignPaths,
    DesignParams,
    SearchMemoryBudget,
    NamedLink,
    OperatorLinks,
    RoleExclusions,
    Tuning,
)

DEFAULT_VERTICES = {
    "AFLCMC": "data/vertices/tenants/aflcmc.csv",
    "AFNWC/NI": "data/vertices/tenants/afnwc_ni.csv",
    "DCN": "data/vertices/carriers/dcn.csv",
    "F-35": "data/vertices/tenants/f_35.csv",
    "Lumen": "data/vertices/carriers/lumen.csv",
    "Providers": "data/vertices/providers/providers.csv",
    "VisionNet": "data/vertices/carriers/vision_net.csv",
}
DEFAULT_CARRIER_EDGES = "data/edges/lumen.csv"
DEFAULT_REGIONAL_EDGES = ["data/edges/dcn.csv", "data/edges/vision_net.csv"]


@dataclass(frozen=True)
class AppConfig:
    """A fully resolved configuration: file paths, design params, pinned edges.

    ``links`` carries the three lists of operator-written links -- pinned mesh pairs,
    forced homes, and pruned mesh pairs -- each still named rather than resolved to ids,
    since resolution needs the graph the overrides layer holds and this one does not.
    """

    paths: DesignPaths
    params: DesignParams
    restrict_backbone_to_datacenters: bool  # required; the handler maps it to a gate or None
    label: str = ""
    links: OperatorLinks = field(default_factory=OperatorLinks)


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


def _required_bool(data: dict[str, Any], key: str) -> bool:
    """Return a required boolean config value, rejecting an absent or non-bool value.

    ``restrict_backbone_to_data_centers`` has no default: every tenant must state whether
    the backbone is gated to data-center cities, so a missing key is an error rather than
    a silently-filled fallback (as with the two redundancy degrees).
    """
    if key not in data:
        raise ValueError(f"config key '{key}' is required and has no default")
    value = data[key]
    if not isinstance(value, bool):
        raise ValueError(f"config key '{key}' must be a boolean")
    return value


def _required_int(data: dict[str, Any], key: str) -> int:
    """Return a required integer config value, rejecting an absent or non-int value.

    The two redundancy degrees (``backbone-mesh-degree``, ``access-homing-degree``)
    have no default: every tenant must state each one, so a missing key is an error
    rather than a silently-filled fallback. ``backbone_coverage_target_miles`` is
    required on the same terms -- every tenant must state how far the backbone must
    grow to cover its demand -- and is an integer because the growth stop test
    compares it against a great-circle haul standing in for a last-mile build, which
    is wrong by tens of miles, so a fraction of one states a resolution the design
    does not have.
    """
    if key not in data:
        raise ValueError(f"config key '{key}' is required and has no default")
    value = data[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"config key '{key}' must be an integer")
    return value


def _connection_list(design: dict[str, Any], key: str) -> tuple[NamedLink, ...]:
    """Parse one list of operator connection mappings, rejecting bad shapes.

    Each entry maps string ``source``/``target`` and nothing else: the key it is written
    under says which tier it acts on, so there is nothing left for the entry to declare.
    An absent ``key`` defaults to an empty list (no connections).
    """
    value = design.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"config key '{key}' must be a list")
    connections: list[NamedLink] = []
    for item in value:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(name), str) for name in ("source", "target")
        ):
            raise ValueError(f"each {key} entry must map source and target to strings")
        connections.append(NamedLink(item["source"], item["target"]))
    return tuple(connections)


def _operator_links(design: dict[str, Any]) -> OperatorLinks:
    """Parse the three lists of operator-written links, one per tier they act on.

    ``forced_connections`` pins mesh pairs, ``forced_homes`` pins a demand vertex onto a
    named backbone node, and ``excluded_connections`` prunes mesh pairs. Each is read the
    same way, because after the split there is nothing tier-specific left to parse -- the
    tiers differ in how the names are resolved, which is the overrides layer's job.
    """
    return OperatorLinks(
        backbone=_connection_list(design, "forced_connections"),
        access=_connection_list(design, "forced_homes"),
        removed_backbone=_connection_list(design, "excluded_connections"),
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


# The keys the settings resource defines. Anything else in a stored settings document
# is an operator typo or a key that has been renamed, and either way the value it holds
# steers nothing -- so it is refused rather than silently replaced by a default.
SETTINGS_KEYS = frozenset({
    "backbone_search_memory_share",
    "bytes_per_backbone_combination",
    "compass_sector_count",
})


def _checked_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Return the settings mapping, rejecting any key the resource does not define."""
    unknown = sorted(set(settings) - SETTINGS_KEYS)
    if unknown:
        raise ValueError(
            f"settings resource carries unknown keys: {', '.join(unknown)}"
        )
    return settings


def _sector_count(settings: dict[str, Any], default: int) -> int:
    """Return the compass sector count, rejecting a non-integer or one below one.

    The count both cuts the compass into sectors and divides the sector tally in the
    strength score, so zero is a division by zero and a fraction is a sector geometry
    nothing can produce. Parse time is the only place either can be refused before a
    design run starts.
    """
    value = settings.get("compass_sector_count", default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("settings key 'compass_sector_count' must be an integer of at least 1")
    return value


def _memory_share(settings: dict[str, Any], default: float) -> float:
    """Return the share of memory the backbone search may use, rejecting a bad value.

    Above 1 the limit authorises more memory than the function has, so a large job is
    killed by the runtime instead of refused cleanly -- the exact failure the setting
    exists to prevent, reached by changing the setting meant to prevent it. At 0 every
    backbone size is refused with an error that talks about a RAM budget and never
    mentions configuration. Parse time is the only point either can be refused before a
    design run starts; failing inside ``enumeration_limit`` would waste the graph load.
    """
    value = settings.get("backbone_search_memory_share", default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("settings key 'backbone_search_memory_share' must be a number")
    if not 0.0 < value <= 1.0:
        raise ValueError(
            "settings key 'backbone_search_memory_share' must be above 0 and at most 1"
        )
    return float(value)


def _tuning(tuning: dict[str, Any], settings: dict[str, Any]) -> Tuning:
    """Resolve the tuning and settings configuration into a :class:`Tuning`.

    The operator's requirements -- the two degrees and the coverage target -- come from
    ``tuning``, which the assembler builds from the ``knobs`` resource and the two
    degree resources. The implementation dials come from ``settings``, and only from
    there: a value left behind under ``knobs`` is not read, so it falls back to the
    dataclass default rather than quietly continuing to steer the search. A settings
    document carrying a key the resource does not define -- a typo, or a name from
    before a rename -- is refused outright, since defaulting past it would run the
    design on values nobody chose (see :func:`_checked_settings`).
    """
    base = Tuning()
    settings = _checked_settings(settings)
    return Tuning(
        compass_sector_count=_sector_count(settings, base.compass_sector_count),
        backbone_mesh_degree=_required_int(tuning, "backbone_mesh_degree"),
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
    design: dict[str, Any], tuning: dict[str, Any], settings: dict[str, Any]
) -> DesignParams:
    """Resolve the design, tuning and settings configuration into :class:`DesignParams`."""
    base = DesignParams()
    return DesignParams(
        min_backbone_count=design.get("min_backbone_count", base.min_backbone_count),
        max_backbone_count=design.get("max_backbone_count", base.max_backbone_count),
        forced_backbone_names=_str_list(design, "forced_backbone", []),
        degree_exempt_backbone_names=_str_list(design, "degree_exempt_backbone", []),
        exclusions=RoleExclusions(
            prohibited_backbone_names=_str_list(design, "prohibited_backbone", []),
        ),
        tuning=_tuning(tuning, settings),
        promote_high_degree_convergences=_required_bool(
            design, "promote_high_degree_convergences_to_backbone_nodes"
        ),
    )


def config_from_data(data: dict[str, Any]) -> AppConfig:
    """Resolve an already-parsed config mapping into a :class:`AppConfig`.

    Any key the mapping omits falls back to the matching built-in default, so a
    partial (even empty) mapping still yields a valid configuration. ``datacenter_cities``
    is threaded by the synthesizer handler, not parsed from these documents.
    """
    design = _mapping(data, "design")
    return AppConfig(
        paths=_paths(_mapping(data, "inputs")),
        params=_params(design, _mapping(data, "tuning"), _mapping(data, "settings")),
        restrict_backbone_to_datacenters=_required_bool(
            design, "restrict_backbone_to_data_centers"
        ),
        label=str(data.get("label", "")),
        links=_operator_links(design),
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
    ``forced-homes``, ``prohibited-connections``, ``backbone-mesh-degree``, ``knobs``,
    ...). This reshapes those documents into the canonical mapping
    :func:`config_from_data` expects and delegates to it, so all parsing and validation
    stays in one place. The two redundancy degrees are required -- a missing one raises
    in :func:`_degree`.

    ``knobs`` carries the operator's coverage target and ``settings`` the
    implementation dials, and the two are passed on separately: nothing merges them, so
    a dial left behind under ``knobs`` is not read at all.
    ``paths`` is left at its defaults: the deployed synthesizer reads its substrate
    from the merged carriers, not from these documents.
    """
    count = _mapping(parts, "backbone-node-count")
    design: dict[str, Any] = {
        "forced_backbone": parts.get("forced-backbone-nodes", []),
        "prohibited_backbone": parts.get("prohibited-backbone-nodes", []),
        "forced_connections": parts.get("forced-connections", []),
        "forced_homes": parts.get("forced-homes", []),
        "excluded_connections": parts.get("prohibited-connections", []),
    }
    placement = _mapping(parts, "backbone-placement")
    if "restrict" in placement:
        design["restrict_backbone_to_data_centers"] = placement["restrict"]
    promotion = _mapping(parts, "convergence-promotion")
    if "promote" in promotion:
        design["promote_high_degree_convergences_to_backbone_nodes"] = promotion["promote"]
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
    return config_from_data({
        "design": design,
        "tuning": tuning,
        "settings": _mapping(parts, "settings"),
        "label": label_text,
    })
