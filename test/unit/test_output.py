"""Unit tests for rendering a design as JSON, CSV, KML, and DOT."""

from __future__ import annotations

import json
from pathlib import Path

import fixtures
from wan_designer.model import Node
from wan_designer.output import (
    dot_escape,
    kml_layer_for_node,
    sorted_physical_edges,
    write_csv,
    write_dot,
    write_json,
    write_kml,
    write_outputs,
)


def _secret_region(name: str) -> Node:
    """Build a cloud secret-region access node with the given name."""
    return Node(
        id=name,
        name=name,
        category="Secret Regions - Cloud Service Providers",
        kind="csp_secret",
        lat=0.0,
        lon=0.0,
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


def test_write_kml_emits_the_five_tier_layers(tmp_path: Path) -> None:
    """Write kml emits one folder per tier layer."""
    path = tmp_path / "d.kml"
    write_kml(path, ARTIFACTS)
    text = path.read_text(encoding="utf-8")
    for name in (
        "Access Nodes",
        "Aggregation Points",
        "Core Nodes",
        "Secret East Regions",
        "Secret West Regions",
    ):
        assert f"<name>{name}</name>" in text


def test_kml_layer_for_node_routes_secret_regions_by_compass() -> None:
    """Secret regions split into east and west layers by name."""
    assert kml_layer_for_node(_secret_region("AWS Secret East Region"), "access") == "secret_east"
    assert kml_layer_for_node(_secret_region("OCI Secret West Region"), "access") == "secret_west"


def test_kml_layer_for_node_omits_directionless_secret() -> None:
    """A secret region without an east/west hint is omitted."""
    assert kml_layer_for_node(_secret_region("Secret Central Region"), "access") is None


def test_kml_layer_for_node_uses_tier_role_for_carrier_pops() -> None:
    """Non-secret nodes map by tier role; transit PoPs are omitted."""
    pop = fixtures.carrier_pop("P0")
    assert kml_layer_for_node(pop, "core") == "core"
    assert kml_layer_for_node(pop, "transit") is None


def test_write_dot_declares_graph(tmp_path: Path) -> None:
    """Write dot declares graph."""
    path = tmp_path / "d.dot"
    write_dot(path, ARTIFACTS)
    assert "graph three_tier_carrier_wan_design" in path.read_text(encoding="utf-8")


def test_dot_escape_escapes_quotes_and_backslashes() -> None:
    """Dot escape escapes quotes and backslashes."""
    assert dot_escape('a"\\b') == 'a\\"\\\\b'


def test_sorted_physical_edges_is_sorted() -> None:
    """Sorted physical edges is sorted."""
    edges = sorted_physical_edges(ARTIFACTS.design)
    assert edges == sorted(edges)
