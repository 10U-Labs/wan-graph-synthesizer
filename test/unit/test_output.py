"""Unit tests for rendering a design as JSON, CSV, KML, and DOT."""

from __future__ import annotations

import json
from pathlib import Path

import fixtures
from wan_designer.output import (
    dot_escape,
    kml_color_for_role,
    sorted_physical_edges,
    write_csv,
    write_dot,
    write_json,
    write_kml,
    write_outputs,
)

ARTIFACTS = fixtures.ring_artifacts()
SOURCES = fixtures.sample_sources()


def test_write_outputs_creates_all_four_files(tmp_path: Path) -> None:
    """Write outputs creates all four files."""
    outputs = write_outputs(tmp_path, SOURCES, ARTIFACTS)
    assert all(path.exists() for path in outputs.values())


def test_write_json_is_valid_json(tmp_path: Path) -> None:
    """Write json is valid json."""
    path = tmp_path / "d.json"
    write_json(path, SOURCES, ARTIFACTS)
    assert "summary" in json.loads(path.read_text(encoding="utf-8"))


def test_write_csv_has_header(tmp_path: Path) -> None:
    """Write csv has header."""
    path = tmp_path / "d.csv"
    write_csv(path, ARTIFACTS)
    assert path.read_text(encoding="utf-8").startswith("source_id,source_name")


def test_write_kml_has_document_name(tmp_path: Path) -> None:
    """Write kml has document name."""
    path = tmp_path / "d.kml"
    write_kml(path, ARTIFACTS)
    assert "Three-Tier Carrier WAN Design" in path.read_text(encoding="utf-8")


def test_write_dot_declares_graph(tmp_path: Path) -> None:
    """Write dot declares graph."""
    path = tmp_path / "d.dot"
    write_dot(path, ARTIFACTS)
    assert "graph three_tier_carrier_wan_design" in path.read_text(encoding="utf-8")


def test_dot_escape_escapes_quotes_and_backslashes() -> None:
    """Dot escape escapes quotes and backslashes."""
    assert dot_escape('a"\\b') == 'a\\"\\\\b'


def test_kml_color_for_role_has_default() -> None:
    """Kml color for role has default."""
    assert kml_color_for_role("unused") == "ffffffff"


def test_sorted_physical_edges_is_sorted() -> None:
    """Sorted physical edges is sorted."""
    edges = sorted_physical_edges(ARTIFACTS.design)
    assert edges == sorted(edges)
