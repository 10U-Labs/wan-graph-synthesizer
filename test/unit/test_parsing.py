"""Unit tests for KML/KMZ and CSV parsing."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

import fixtures
from wan_designer.model import Node
from wan_designer.parsing import (
    build_adjacency,
    clean_description,
    load_carrier_edges,
    load_nodes,
    load_pop_roles,
    read_kml_root,
)

DUP_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document><name>D</name>
    <Folder><name>Carrier 400G PoPs</name>
      <Placemark><name>Twin</name>
        <Point><coordinates>-90,39,0</coordinates></Point></Placemark>
      <Placemark><name>Twin</name>
        <Point><coordinates>-91,38,0</coordinates></Point></Placemark>
    </Folder>
  </Document>
</kml>
"""

NO_DOCUMENT_KML = '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"/>'


def kml_file(tmp_path: Path, text: str) -> Path:
    """Write KML text to a temp file and return its path."""
    path = tmp_path / "doc.kml"
    path.write_text(text, encoding="utf-8")
    return path


def kmz_file(tmp_path: Path, members: dict[str, str]) -> Path:
    """Write a .kmz archive from name->text members."""
    path = tmp_path / "doc.kmz"
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return path


def carrier_names(nodes: list[Node]) -> set[str]:
    """Names of the carrier PoP nodes."""
    return {node.name for node in nodes if node.kind == "carrier_pop"}


def test_read_kml_root_reads_kml_file(tmp_path: Path) -> None:
    """Read kml root reads kml file."""
    root = read_kml_root(kml_file(tmp_path, fixtures.SAMPLE_KML))
    assert root.tag.endswith("kml")


def test_read_kml_root_reads_kmz_file(tmp_path: Path) -> None:
    """Read kml root reads kmz file."""
    root = read_kml_root(kmz_file(tmp_path, {"doc.kml": fixtures.SAMPLE_KML}))
    assert root.tag.endswith("kml")


def test_read_kml_root_prefers_doc_kml(tmp_path: Path) -> None:
    """Read kml root prefers doc kml."""
    archive = kmz_file(tmp_path, {"other.kml": NO_DOCUMENT_KML, "doc.kml": fixtures.SAMPLE_KML})
    assert read_kml_root(archive).find("{http://www.opengis.net/kml/2.2}Document") is not None


def test_read_kml_root_rejects_kmz_without_kml(tmp_path: Path) -> None:
    """Read kml root rejects kmz without kml."""
    with pytest.raises(ValueError):
        read_kml_root(kmz_file(tmp_path, {"readme.txt": "hi"}))


def test_read_kml_root_rejects_unknown_suffix(tmp_path: Path) -> None:
    """Read kml root rejects unknown suffix."""
    bad = tmp_path / "data.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        read_kml_root(bad)


def test_clean_description_handles_empty() -> None:
    """Clean description handles empty."""
    assert clean_description(None) == ""


def test_clean_description_strips_markup() -> None:
    """Clean description strips markup."""
    assert clean_description("<b>a</b><br/>b") == "a\nb"


def test_load_nodes_counts_all_placemarks(tmp_path: Path) -> None:
    """Load nodes counts all placemarks."""
    nodes = load_nodes(kml_file(tmp_path, fixtures.SAMPLE_KML))
    assert len(nodes) == 4


def test_load_nodes_classifies_carrier_pops(tmp_path: Path) -> None:
    """Load nodes classifies carrier pops."""
    nodes = load_nodes(kml_file(tmp_path, fixtures.SAMPLE_KML))
    assert carrier_names(nodes) == {"Denver, CO", "Kansas City, MO"}


def test_load_nodes_deduplicates_ids(tmp_path: Path) -> None:
    """Load nodes deduplicates ids."""
    nodes = load_nodes(kml_file(tmp_path, DUP_KML))
    assert len({node.id for node in nodes}) == 2


def test_load_nodes_requires_document(tmp_path: Path) -> None:
    """Load nodes requires document."""
    with pytest.raises(ValueError):
        load_nodes(kml_file(tmp_path, NO_DOCUMENT_KML))


def test_load_pop_roles_defaults_to_aggregator() -> None:
    """Load pop roles defaults to aggregator."""
    pops = [fixtures.carrier_pop("Denver, CO")]
    roles = load_pop_roles(None, pops)
    assert roles[pops[0].id] == "aggregator"


def test_load_pop_roles_reads_file(tmp_path: Path) -> None:
    """Load pop roles reads file."""
    pops = [fixtures.carrier_pop("Denver, CO")]
    path = tmp_path / "roles.csv"
    path.write_text('name,role\n"Denver, CO",roadm\n', encoding="utf-8")
    assert load_pop_roles(path, pops)[pops[0].id] == "roadm"


def test_load_pop_roles_rejects_unknown_name(tmp_path: Path) -> None:
    """Load pop roles rejects unknown name."""
    path = tmp_path / "roles.csv"
    path.write_text("name,role\nNowhere,roadm\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_pop_roles(path, [fixtures.carrier_pop("Denver, CO")])


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
