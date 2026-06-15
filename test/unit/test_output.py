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


def _region(name: str, kind: str) -> Node:
    """Build a classified-region access node of the given kind and name."""
    return Node(id=name, name=name, category=name, kind=kind, lat=0.0, lon=0.0)


def _provider regions(name: str) -> Node:
    """Build a cloud provider regions access node with the given name."""
    return _region(name, "provider")

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


def test_write_kml_emits_every_tier_layer(tmp_path: Path) -> None:
    """Write kml emits one folder per tier layer."""
    path = tmp_path / "d.kml"
    write_kml(path, ARTIFACTS)
    text = path.read_text(encoding="utf-8")
    for name in (
        "Access Nodes",
        "Aggregation Points",
        "Core Nodes",
        "provider region",
        "provider region",
        "provider region",
        "provider region",
        "provider region",
        "provider region",
    ):
        assert f"<name>{name}</name>" in text


def test_kml_layer_for_node_routes_provider region() -> None:
    """An provider region maps to the provider region."""
    assert kml_layer_for_node(_provider regions("Provider Region"), "access") == "provider region"


def test_kml_layer_for_node_routes_provider region() -> None:
    """A provider region maps to the provider region."""
    assert kml_layer_for_node(_provider regions("Provider Region"), "access") == "provider region"


def test_kml_layer_for_node_omits_directionless_secret() -> None:
    """A provider regions without an regions hint is omitted."""
    assert kml_layer_for_node(_provider regions("provider Central Region"), "access") is None


def test_kml_layer_for_node_routes_provider regions() -> None:
    """provider regions split regions into their own layers."""
    assert kml_layer_for_node(_region("provider region", "provider regions"), "access") == "provider region"
    assert kml_layer_for_node(_region("provider region", "provider regions"), "access") == "provider region"


def test_kml_layer_for_node_routes_provider regions() -> None:
    """provider regions split regions into their own layers."""
    assert kml_layer_for_node(_region("provider region", "provider_region"), "access") == "ts_east"
    assert kml_layer_for_node(_region("provider region", "provider_region"), "access") == "ts_west"


def test_kml_layer_for_node_uses_tier_role_for_carrier_pops() -> None:
    """Non-provider nodes map by their tier role."""
    assert kml_layer_for_node(fixtures.carrier_pop("P0"), "core") == "core"


def test_kml_layer_for_node_omits_transit_pops() -> None:
    """Transit PoPs are not assigned to any output layer."""
    assert kml_layer_for_node(fixtures.carrier_pop("P0"), "transit") is None


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
