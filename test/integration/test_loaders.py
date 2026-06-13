"""Integration tests for loading nodes and edges from on-disk files."""

from __future__ import annotations

from pathlib import Path

import pytest

from design_lumen_network import Node, load_lumen_edges, load_nodes

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Top</name>
    <Folder>
      <name>Lumen 400G PoPs</name>
      <Placemark>
        <name>Denver, CO</name>
        <Point><coordinates>-104.9903,39.7392,0</coordinates></Point>
      </Placemark>
      <Placemark>
        <name>Kansas City, MO</name>
        <Point><coordinates>-94.5786,39.0997,0</coordinates></Point>
      </Placemark>
    </Folder>
    <Folder>
      <name>F-35 CONUS Installations</name>
      <Placemark>
        <name>Buckley</name>
        <Point><coordinates>-104.75,39.7,0</coordinates></Point>
      </Placemark>
    </Folder>
  </Document>
</kml>
"""

EDGES_CSV = """source,target,source_page,note
"Denver, CO","Kansas City, MO",overview,visible route
"""


@pytest.fixture(name="nodes", scope="module")
def fixture_nodes(tmp_path_factory: pytest.TempPathFactory) -> list[Node]:
    """Fixture providing the nodes."""
    path = tmp_path_factory.mktemp("kml") / "doc.kml"
    path.write_text(KML, encoding="utf-8")
    return load_nodes(path)


def test_loads_all_placemarks(nodes: list[Node]) -> None:
    """Loads all placemarks."""
    assert len(nodes) == 3


def test_classifies_lumen_pops(nodes: list[Node]) -> None:
    """Classifies lumen pops."""
    assert sum(1 for node in nodes if node.kind == "lumen_pop") == 2


def test_classifies_access_node(nodes: list[Node]) -> None:
    """Classifies access node."""
    assert any(node.kind == "f35" for node in nodes)


def test_loads_edge_with_computed_distance(
    nodes: list[Node], tmp_path: Path
) -> None:
    """Loads edge with computed distance."""
    lumen_pops = [node for node in nodes if node.kind == "lumen_pop"]
    csv_path = tmp_path / "edges.csv"
    csv_path.write_text(EDGES_CSV, encoding="utf-8")
    edges = load_lumen_edges(csv_path, lumen_pops)
    distance = next(iter(edges.values())).distance_miles
    assert distance == pytest.approx(558.0, abs=20.0)
