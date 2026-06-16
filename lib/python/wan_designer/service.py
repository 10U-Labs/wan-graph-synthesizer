"""Compute-on-demand design service backing the REST API.

The optimizer is invoked here, once per WAN map, and the resulting design
payload is memoized in an in-process cache so the atomic endpoints can each
serve a slice of one shared computation without re-running the (deterministic,
file-driven) design. This module is the sole place the design is computed; the
REST API is the sole interface that drives it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from wan_designer.config import load_config
from wan_designer.installations import realize_installations
from wan_designer.model import (
    DesignPaths,
    DesignArtifacts,
    DesignParams,
    ForcedConnection,
    PhysicalEdge,
    SourceFiles,
    carrier_role,
    is_carrier_pop,
)
from wan_designer.optimize import optimize_three_tier_design
from wan_designer.overrides import apply_role_overrides, materialize_selected_colocation_twins
from wan_designer.output import design_payload
from wan_designer.parsing import load_carrier_edges, load_vertices
from wan_designer.validation import augment_physical_resilience, validate_design

logger = logging.getLogger(__name__)


def run_design(
    paths: DesignPaths,
    params: DesignParams,
    augment: bool,
    forced_connections: tuple[ForcedConnection, ...] = (),
) -> DesignArtifacts:
    """Load inputs, optimize the three-tier design, and validate it."""
    vertices = load_vertices(list(paths.vertex_files))
    if not vertices:
        raise ValueError("No vertices found in the configured vertex files")
    carrier_pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    physical_edges: dict[tuple[str, str], PhysicalEdge] = {}
    for edge_path in (paths.edge_path, *paths.regional_edge_paths):
        physical_edges.update(load_carrier_edges(edge_path, carrier_pops))
    realized = realize_installations(
        vertices, physical_edges, frozenset(params.forced_aggregation_names)
    )
    vertices, physical_edges = realized.vertices, realized.physical_edges
    roles = {pop.id: carrier_role(pop) for pop in vertices if is_carrier_pop(pop)}
    vertices, physical_edges, overrides = apply_role_overrides(
        vertices, physical_edges, params, forced_connections
    )
    logger.info(
        "Loaded %d vertices and %d physical edges; starting optimization",
        len(vertices), len(physical_edges),
    )
    design = optimize_three_tier_design(vertices, physical_edges, roles, params, overrides)
    logger.info("Optimization done; validating the design")
    vertices, physical_edges = materialize_selected_colocation_twins(
        vertices, physical_edges, design
    )
    if augment:
        design = augment_physical_resilience(vertices, physical_edges, design)
    validation = validate_design(vertices, design)
    return DesignArtifacts(vertices, physical_edges, design, validation)


def available_wan_maps(config_dir: Path) -> list[dict[str, str]]:
    """List the selectable WAN maps in ``config_dir`` as ``{id, label}`` entries."""
    entries: list[dict[str, str]] = []
    for path in sorted(config_dir.glob("*.yml")):
        config = load_config(path)
        entries.append({"id": path.stem, "label": config.label or path.stem})
    return entries


def design_for_wan_map(
    config_dir: Path, wan_map_id: str, cache: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Return the memoized design payload for ``wan_map_id`` under ``config_dir``.

    Unknown ids -- including any path-traversal attempt -- raise ``KeyError``,
    since ``wan_map_id`` must match one of the WAN maps discovered in the directory.
    """
    if wan_map_id in cache:
        return cache[wan_map_id]
    if wan_map_id not in {entry["id"] for entry in available_wan_maps(config_dir)}:
        raise KeyError(wan_map_id)
    config = load_config(config_dir / f"{wan_map_id}.yml")
    artifacts = run_design(
        config.paths, config.params, config.resilience_augmentation, config.forced_connections
    )
    sources = SourceFiles(
        tuple(path for _tenant, path in config.paths.vertex_files),
        config.paths.edge_path,
    )
    payload = design_payload(sources, artifacts)
    cache[wan_map_id] = payload
    return payload
