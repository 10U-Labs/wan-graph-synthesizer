"""Unit tests for the compute-on-demand WAN map service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import fixtures
from wan_designer.service import available_wan_maps, design_for_wan_map


def test_available_wan_maps_defaults_label_to_stem(tmp_path: Path) -> None:
    """A config without a label is listed under its file stem."""
    fixtures.write_solvable_config(tmp_path)
    assert available_wan_maps(tmp_path) == [{"id": "joint", "label": "joint"}]


def test_available_wan_maps_uses_declared_label(tmp_path: Path) -> None:
    """A config's declared label is surfaced over its file stem."""
    (tmp_path / "f_35.yml").write_text("label: F-35\n", encoding="utf-8")
    assert available_wan_maps(tmp_path) == [{"id": "f_35", "label": "F-35"}]


def test_design_for_wan_map_returns_payload(tmp_path: Path) -> None:
    """Computing a known WAN map returns a payload carrying the vertices slice."""
    fixtures.write_solvable_config(tmp_path, core_count=2)
    cache: dict[str, Any] = {}
    assert "vertices" in design_for_wan_map(tmp_path, "joint", cache)


def test_design_for_wan_map_caches(tmp_path: Path) -> None:
    """A second request returns the cached payload object, not a recomputation."""
    fixtures.write_solvable_config(tmp_path, core_count=2)
    cache: dict[str, Any] = {}
    first = design_for_wan_map(tmp_path, "joint", cache)
    assert design_for_wan_map(tmp_path, "joint", cache) is first


def test_design_for_wan_map_rejects_unknown_id(tmp_path: Path) -> None:
    """An unknown WAN map id raises KeyError before any computation."""
    fixtures.write_solvable_config(tmp_path)
    with pytest.raises(KeyError):
        design_for_wan_map(tmp_path, "nope", {})
