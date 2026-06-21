"""Unit tests for loading vertices and carrier edges from CSV."""

from __future__ import annotations

from pathlib import Path

import pytest

import fixtures
from wan_designer import Vertex, is_carrier_pop, is_justified_aggregation
from wan_designer.parsing import build_adjacency, load_carrier_edges, load_vertices

def carrier_names(vertices: list[Vertex]) -> set[str]:
    """Names of the carrier PoP vertices."""
    return {vertex.name for vertex in vertices if is_carrier_pop(vertex)}


def _justified_by_name(tmp_path: Path, name: str) -> Vertex:
    """Load the justified-column fixture and return the vertex with ``name``."""
    tenant, path = fixtures.write_justified_vertices(tmp_path)
    return next(vertex for vertex in load_vertices([(tenant, path)]) if vertex.name == name)


def test_load_vertices_reads_justified_yes(tmp_path: Path) -> None:
    """A justified installation row sets the justified_aggregation flag."""
    assert _justified_by_name(tmp_path, "Luke AFB").info.justified_aggregation is True


def test_is_justified_aggregation_false_for_no(tmp_path: Path) -> None:
    """An installation marked 'no' is not a justified aggregation."""
    assert is_justified_aggregation(_justified_by_name(tmp_path, "Crystal City, VA")) is False


def test_is_justified_aggregation_ignores_carrier_pops(tmp_path: Path) -> None:
    """A carrier PoP is never a justified aggregation, even with the column set."""
    assert is_justified_aggregation(_justified_by_name(tmp_path, "Denver, CO")) is False


def test_load_vertices_defaults_missing_justified_column(tmp_path: Path) -> None:
    """Files without the justified column default installations to not-justified."""
    vertex_files = fixtures.write_sample_inputs(tmp_path)[0]
    buckley = next(v for v in load_vertices(list(vertex_files)) if v.name == "Buckley")
    assert is_justified_aggregation(buckley) is False


def test_load_vertices_reads_every_file(tmp_path: Path) -> None:
    """Load vertices reads every row across all tenant files."""
    vertex_files = fixtures.write_sample_inputs(tmp_path)[0]
    assert len(load_vertices(list(vertex_files))) == 4


def test_load_vertices_assigns_tenant_from_file(tmp_path: Path) -> None:
    """The tenant comes from the file's pairing, and kind from the row."""
    vertex_files = fixtures.write_sample_inputs(tmp_path)[0]
    buckley = next(v for v in load_vertices(list(vertex_files)) if v.name == "Buckley")
    assert (buckley.tenant, buckley.kind) == ("F-35", "Military installation")


def test_load_vertices_identifies_carrier_pops(tmp_path: Path) -> None:
    """PoP/ROADM kinds are carrier PoPs; installations are not."""
    vertex_files = fixtures.write_sample_inputs(tmp_path)[0]
    assert carrier_names(load_vertices(list(vertex_files))) == {"Denver, CO", "Kansas City, MO"}


def test_load_vertices_parses_shown_in_map(tmp_path: Path) -> None:
    """The shown_in_map column maps to a boolean on each vertex."""
    by_name = {v.name: v for v in load_vertices(list(fixtures.write_sample_inputs(tmp_path)[0]))}
    assert (by_name["Denver, CO"].shown_in_map, by_name["Buckley"].shown_in_map) == (False, True)


def test_load_vertices_reads_municipality_and_state(tmp_path: Path) -> None:
    """The municipality and state columns load onto each vertex."""
    path = tmp_path / "f35.csv"
    path.write_text(
        "name,latitude,longitude,kind,shown_in_map,description,municipality,state\n"
        "Dannelly Field,32.3,-86.4,Military installation,Shown in map,,Montgomery,AL\n",
        encoding="utf-8",
    )
    vertex = load_vertices([("F-35", path)])[0]
    assert (vertex.info.municipality, vertex.info.state) == ("Montgomery", "AL")


def test_load_vertices_defaults_missing_location_columns(tmp_path: Path) -> None:
    """Files without the location columns parse with empty municipality/state."""
    vertex_files = fixtures.write_sample_inputs(tmp_path)[0]
    vertex = load_vertices(list(vertex_files))[0]
    assert (vertex.info.municipality, vertex.info.state) == ("", "")


def test_load_vertices_deduplicates_ids_across_files(tmp_path: Path) -> None:
    """The same name in two tenant files yields two distinct ids."""
    row = [("Twin", 39.0, -90.0, "PoP", "Not shown in map", "")]
    vertex_files = fixtures.write_vertex_files(tmp_path, {"Lumen": row, "DCN": row})
    vertices = load_vertices(list(vertex_files))
    assert len({vertex.id for vertex in vertices}) == 2


def test_load_vertices_requires_existing_file(tmp_path: Path) -> None:
    """Load vertices rejects a missing file."""
    with pytest.raises(ValueError):
        load_vertices([("Lumen", tmp_path / "missing.csv")])


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
