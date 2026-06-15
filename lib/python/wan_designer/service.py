"""Compute-on-demand design service backing the REST API.

The optimizer is invoked here, once per config, and the resulting design payload
is memoized in an in-process cache so the atomic endpoints can each serve a slice
of one shared computation without re-running the (deterministic, file-driven)
design.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wan_designer.cli import run_design
from wan_designer.config import load_config
from wan_designer.model import SourceFiles
from wan_designer.output import design_payload


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
