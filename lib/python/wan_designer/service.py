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

from wan_designer import stages
from wan_designer.config import load_config
from wan_designer.model import (
    DesignArtifacts,
    DesignParams,
    DesignPaths,
    ForcedConnection,
    SourceFiles,
    carrier_role,
    is_carrier_pop,
)
from wan_designer.offnet import load_off_net_sites
from wan_designer.optimize import optimize_three_tier_design
from wan_designer.output import design_payload
from wan_designer.overrides import apply_role_overrides

logger = logging.getLogger(__name__)


def run_design(
    paths: DesignPaths,
    params: DesignParams,
    augment: bool,
    forced_connections: tuple[ForcedConnection, ...] = (),
    excluded_connections: tuple[ForcedConnection, ...] = (),
) -> DesignArtifacts:
    """Load inputs, optimize the three-tier design, and validate it."""
    vertices, physical_edges = stages.load_inputs(paths)
    off_net_sites = load_off_net_sites(paths.off_net_path) if paths.off_net_path else []
    vertices, physical_edges = stages.dual_home(
        vertices, physical_edges, params, off_net_sites
    )
    roles = {pop.id: carrier_role(pop) for pop in vertices if is_carrier_pop(pop)}
    vertices, physical_edges, overrides = apply_role_overrides(
        vertices, physical_edges, params, forced_connections, excluded_connections
    )
    logger.info(
        "Loaded %d vertices and %d physical edges; starting optimization",
        len(vertices), len(physical_edges),
    )
    design = optimize_three_tier_design(vertices, physical_edges, roles, params, overrides)
    logger.info("Optimization done; validating the design")
    vertices, physical_edges, design, validation = stages.finalize(
        vertices, physical_edges, design, params, augment
    )
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
        config.paths,
        config.params,
        config.resilience_augmentation,
        config.forced_connections,
        config.excluded_connections,
    )
    sources = SourceFiles(
        tuple(path for _tenant, path in config.paths.vertex_files),
        config.paths.edge_path,
    )
    payload = design_payload(sources, artifacts)
    cache[wan_map_id] = payload
    return payload
