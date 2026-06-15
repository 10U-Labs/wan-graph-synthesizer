"""Unit tests for loading vertices and carrier edges from CSV."""

from __future__ import annotations

from pathlib import Path

import pytest

import fixtures
from wan_designer import Vertex, is_carrier_pop
from wan_designer.parsing import build_adjacency, load_carrier_edges, load_vertices

VERTICES_CSV = (
    "name,latitude,longitude,tenant,kind,shown_in_map,description\n"
    '"Denver, CO",39.7392,-104.9903,Lumen,PoP,Not shown in map,a Lumen PoP\n'
    '"Kansas City, MO",39.0997,-94.5786,Lumen,ROADM,Not shown in map,\n'
    "Buckley,39.7,-104.75,F-35,Military installation,Shown in map,\n"
)

DUP_VERTICES_CSV = (
    "name,latitude,longitude,tenant,kind,shown_in_map,description\n"
    "Twin,39,-90,Lumen,PoP,Not shown in map,\n"
    "Twin,38,-91,Lumen,PoP,Not shown in map,\n"
)


def vertices_file(tmp_path: Path, text: str = VERTICES_CSV) -> Path:
    """Write a vertices CSV to a temp file and return its path."""
    path = tmp_path / "vertices.csv"
    path.write_text(text, encoding="utf-8")
    return path


def carrier_names(vertices: list[Vertex]) -> set[str]:
    """Names of the carrier PoP vertices."""
    return {vertex.name for vertex in vertices if is_carrier_pop(vertex)}


def test_load_vertices_reads_all_rows(tmp_path: Path) -> None:
    """Load vertices reads every row."""
    assert len(load_vertices(vertices_file(tmp_path))) == 3


def test_load_vertices_reads_tenant_and_kind(tmp_path: Path) -> None:
    """Load vertices reads tenant and kind from the row."""
    buckley = next(v for v in load_vertices(vertices_file(tmp_path)) if v.name == "Buckley")
    assert (buckley.tenant, buckley.kind) == ("F-35", "Military installation")


def test_load_vertices_identifies_carrier_pops(tmp_path: Path) -> None:
    """PoP and ROADM kinds are carrier PoPs; installations are not."""
    assert carrier_names(load_vertices(vertices_file(tmp_path))) == {
        "Denver, CO",
        "Kansas City, MO",
    }


def test_load_vertices_parses_shown_in_map(tmp_path: Path) -> None:
    """The shown_in_map column maps to a boolean on each vertex."""
    by_name = {v.name: v for v in load_vertices(vertices_file(tmp_path))}
    assert (by_name["Denver, CO"].shown_in_map, by_name["Buckley"].shown_in_map) == (False, True)


def test_load_vertices_deduplicates_ids(tmp_path: Path) -> None:
    """Two vertices that slug to the same id get distinct ids."""
    vertices = load_vertices(vertices_file(tmp_path, DUP_VERTICES_CSV))
    assert len({vertex.id for vertex in vertices}) == 2


def test_load_vertices_requires_existing_file(tmp_path: Path) -> None:
    """Load vertices rejects a missing file."""
    with pytest.raises(ValueError):
        load_vertices(tmp_path / "missing.csv")


def test_load_carrier_edges_requires_existing_file(tmp_path: Path) -> None:
    """Load carrier edges requires existing file."""
    with pytest.raises(ValueError):
        load_carrier_edges(tmp_path / "missing.csv", [])


def test_load_carrier_edges_uses_given_distance(tmp_path: Path) -> None:
    """Load carrier edges uses given distance."""
    pops = [fixtures.carrier_pop("Denver, CO"), fixtures.carrier_pop("Kansas City, MO")]
    path = tmp_path / "e.csv"
    path.write_text(
        'source,target,distance_miles\n"Denver, CO","Kansas City, MO",12.5\n',
        encoding="utf-8",
    )
    edges = load_carrier_edges(path, pops)
    assert next(iter(edges.values())).distance_miles == 12.5


def test_load_carrier_edges_computes_distance(tmp_path: Path) -> None:
    """Load carrier edges computes distance."""
    pops = [
        fixtures.carrier_pop("Denver, CO", 39.7392, -104.9903),
        fixtures.carrier_pop("Kansas City, MO", 39.0997, -94.5786),
    ]
    path = tmp_path / "e.csv"
    path.write_text(fixtures.SAMPLE_EDGES_CSV, encoding="utf-8")
    edges = load_carrier_edges(path, pops)
    assert next(iter(edges.values())).distance_miles == pytest.approx(558.0, abs=20.0)


def test_load_carrier_edges_rejects_unknown_source(tmp_path: Path) -> None:
    """Load carrier edges rejects unknown source."""
    path = tmp_path / "e.csv"
    path.write_text('source,target\nNowhere,"Kansas City, MO"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_carrier_edges(path, [fixtures.carrier_pop("Kansas City, MO")])


def test_load_carrier_edges_rejects_unknown_target(tmp_path: Path) -> None:
    """Load carrier edges rejects unknown target."""
    path = tmp_path / "e.csv"
    path.write_text('source,target\n"Denver, CO",Nowhere\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_carrier_edges(path, [fixtures.carrier_pop("Denver, CO")])


def test_build_adjacency_is_bidirectional() -> None:
    """Build adjacency is bidirectional."""
    edges = fixtures.ring_physical_edges()
    adjacency = build_adjacency(edges)
    assert ("P1", 100.0) in adjacency["P0"] and ("P0", 100.0) in adjacency["P1"]
