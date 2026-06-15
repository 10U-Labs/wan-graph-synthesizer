"""Integration tests for loading vertices and edges from on-disk files."""

from __future__ import annotations

from pathlib import Path

import pytest

import fixtures
from wan_designer import Vertex, is_carrier_pop, load_carrier_edges, load_vertices


@pytest.fixture(name="vertices", scope="module")
def fixture_vertices(tmp_path_factory: pytest.TempPathFactory) -> list[Vertex]:
    """Fixture providing the vertices parsed from the sample CSV."""
    vertices_csv, _edges = fixtures.write_sample_inputs(tmp_path_factory.mktemp("vertices"))
    return load_vertices(vertices_csv)


def test_loads_all_vertices(vertices: list[Vertex]) -> None:
    """Loads every row of the vertices CSV."""
    assert len(vertices) == 4


def test_classifies_two_carrier_pops(vertices: list[Vertex]) -> None:
    """Classifies two carrier pops."""
    assert sum(1 for vertex in vertices if is_carrier_pop(vertex)) == 2


def test_loads_edge_between_pops(vertices: list[Vertex], tmp_path: Path) -> None:
    """Loads edge between pops."""
    pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    _vertices_csv, edges_path = fixtures.write_sample_inputs(tmp_path)
    assert len(load_carrier_edges(edges_path, pops)) == 1
