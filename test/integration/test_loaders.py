"""Integration tests for loading nodes and edges from on-disk files."""

from __future__ import annotations

from pathlib import Path

import pytest

import fixtures
from wan_designer import Node, load_carrier_edges, load_nodes


@pytest.fixture(name="nodes", scope="module")
def fixture_nodes(tmp_path_factory: pytest.TempPathFactory) -> list[Node]:
    """Fixture providing the nodes parsed from the sample KML."""
    kml, _edges = fixtures.write_sample_inputs(tmp_path_factory.mktemp("kml"))
    return load_nodes(kml)


def test_loads_all_geometry_placemarks(nodes: list[Node]) -> None:
    """Loads all geometry placemarks."""
    assert len(nodes) == 4


def test_classifies_two_carrier_pops(nodes: list[Node]) -> None:
    """Classifies two carrier pops."""
    assert sum(1 for node in nodes if node.kind == "carrier_pop") == 2


def test_loads_edge_between_pops(nodes: list[Node], tmp_path: Path) -> None:
    """Loads edge between pops."""
    pops = [node for node in nodes if node.kind == "carrier_pop"]
    _kml, edges_path = fixtures.write_sample_inputs(tmp_path)
    assert len(load_carrier_edges(edges_path, pops)) == 1
