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
from wan_designer.model import (
    DesignPaths,
    DesignArtifacts,
    DesignParams,
    PhysicalEdge,
    SourceFiles,
    Vertex,
    carrier_role,
    is_carrier_pop,
)
from wan_designer.optimize import apply_role_overrides, optimize_three_tier_design
from wan_designer.output import design_payload
from wan_designer.parsing import load_carrier_edges, load_vertices
from wan_designer.population import (
    RealizedAnchors,
    access_states,
    carrier_states,
    load_county_populations,
    load_municipalities,
    population_placements,
    realize_anchors,
)
from wan_designer.validation import augment_physical_resilience, validate_design

logger = logging.getLogger(__name__)


def _resolve_population_anchors(
    county_path: Path,
    municipality_path: Path,
    params: DesignParams,
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> RealizedAnchors:
    """Resolve and realize the population anchors for the in-scope states."""
    carrier_pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    access_vertices = [vertex for vertex in vertices if not is_carrier_pop(vertex)]
    scope = set(params.population.states) or carrier_states(carrier_pops)
    placements = population_placements(
        carrier_pops,
        access_states(access_vertices, carrier_pops),
        load_county_populations(county_path),
        load_municipalities(municipality_path),
        scope,
    )
    return realize_anchors(placements, vertices, physical_edges)


def run_design(paths: DesignPaths, params: DesignParams, augment: bool) -> DesignArtifacts:
    """Load inputs, optimize the three-tier design, and validate it."""
    vertices = load_vertices(list(paths.vertex_files))
    if not vertices:
        raise ValueError("No vertices found in the configured vertex files")
    carrier_pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    physical_edges: dict[tuple[str, str], PhysicalEdge] = {}
    for edge_path in (paths.edge_path, *paths.regional_edge_paths):
        physical_edges.update(load_carrier_edges(edge_path, carrier_pops))
    roles = {pop.id: carrier_role(pop) for pop in carrier_pops}
    anchors: RealizedAnchors | None = None
    county_path, municipality_path = paths.county_populations, paths.municipality_populations
    if params.population.enabled and county_path is not None and municipality_path is not None:
        anchors = _resolve_population_anchors(
            county_path, municipality_path, params, vertices, physical_edges
        )
        vertices, physical_edges = anchors.vertices, anchors.physical_edges
    vertices, physical_edges, overrides = apply_role_overrides(
        vertices, physical_edges, params, anchors
    )
    logger.info(
        "Loaded %d vertices and %d physical edges; starting optimization",
        len(vertices), len(physical_edges),
    )
    design = optimize_three_tier_design(vertices, physical_edges, roles, params, overrides)
    logger.info("Optimization done; validating the design")
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
    artifacts = run_design(config.paths, config.params, config.resilience_augmentation)
    sources = SourceFiles(
        tuple(path for _tenant, path in config.paths.vertex_files),
        config.paths.edge_path,
        config.paths.mapbook_pdf,
    )
    payload = design_payload(sources, artifacts)
    cache[wan_map_id] = payload
    return payload
