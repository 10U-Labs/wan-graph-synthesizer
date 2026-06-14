"""Parse KMZ/KML placemarks and the carrier edge CSV into the data model."""

from __future__ import annotations

import csv
import html
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from wan_designer.model import (
    KML_NS,
    Node,
    PhysicalEdge,
    classify_category,
    edge_key,
    haversine_miles,
    slugify,
)


def read_kml_root(input_path: Path) -> ET.Element:
    """Parse the root KML element from a .kmz or .kml file."""
    if input_path.suffix.lower() == ".kmz":
        with zipfile.ZipFile(input_path) as archive:
            kml_names = [name for name in archive.namelist() if name.lower().endswith(".kml")]
            if not kml_names:
                raise ValueError(f"{input_path} does not contain a .kml file")
            preferred = "doc.kml" if "doc.kml" in kml_names else kml_names[0]
            return ET.fromstring(archive.read(preferred))
    if input_path.suffix.lower() == ".kml":
        return ET.parse(input_path).getroot()
    raise ValueError(f"Unsupported input type: {input_path}. Expected .kmz or .kml")

def clean_description(raw_text: str | None) -> str:
    """Strip HTML markup from a placemark description into plain text."""
    if not raw_text:
        return ""
    text = html.unescape(raw_text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)

def parse_point_placemark(placemark: ET.Element, category: str, used_ids: set[str]) -> Node | None:
    """Parse one point placemark into a Node, or None if it has no point."""
    coordinates = placemark.find(".//k:Point/k:coordinates", KML_NS)
    if coordinates is None or not coordinates.text or not coordinates.text.strip():
        return None

    lon_text, lat_text, *_ = coordinates.text.strip().split(",")
    name = placemark.findtext("k:name", default="Unnamed", namespaces=KML_NS).strip()
    kind = classify_category(category)
    base_id = f"{kind}_{slugify(name)}"
    node_id = base_id
    suffix = 2
    while node_id in used_ids:
        node_id = f"{base_id}_{suffix}"
        suffix += 1
    used_ids.add(node_id)

    return Node(
        id=node_id,
        name=name,
        category=category,
        kind=kind,
        lat=float(lat_text),
        lon=float(lon_text),
        description=clean_description(
            placemark.findtext("k:description", default="", namespaces=KML_NS)
        ),
    )

def load_nodes(input_path: Path) -> list[Node]:
    """Load every point placemark from the KMZ/KML as a list of nodes."""
    root = read_kml_root(input_path)
    document = root.find("k:Document", KML_NS)
    if document is None:
        raise ValueError("KML document does not contain a Document element")

    document_name = document.findtext(
        "k:name", default="Top Level Placemarks", namespaces=KML_NS
    ).strip()
    nodes: list[Node] = []
    used_ids: set[str] = set()

    for placemark in document.findall("k:Placemark", KML_NS):
        node = parse_point_placemark(placemark, document_name, used_ids)
        if node is not None:
            nodes.append(node)

    for folder in document.findall("k:Folder", KML_NS):
        category = folder.findtext("k:name", default="Folder", namespaces=KML_NS).strip()
        for placemark in folder.findall("k:Placemark", KML_NS):
            node = parse_point_placemark(placemark, category, used_ids)
            if node is not None:
                nodes.append(node)

    return nodes

def load_regional_nodes(path: Path) -> list[Node]:
    """Load regional carrier PoPs (DCN, Vision Net) with their coordinates.

    Each row is ``name,lat,lon,network``. Nodes are Carrier PoPs whose
    category records which regional network they belong to; names are
    curated to be unique across the regional files.
    """
    if not path.exists():
        raise ValueError(f"Regional node file does not exist: {path}")
    nodes: list[Node] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = row["name"].strip()
            nodes.append(
                Node(
                    id=f"carrier_pop_{slugify(name)}",
                    name=name,
                    category=row["network"].strip(),
                    kind="carrier_pop",
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                )
            )
    return nodes

def load_regional_networks(
    node_path: Path,
    edge_paths: list[Path],
    lumen_pops: list[Node],
) -> tuple[list[Node], dict[tuple[str, str], PhysicalEdge], dict[str, str]]:
    """Load regional carriers and stitch them onto the Lumen PoP set.

    Returns the regional nodes, all their edges (including interconnect
    edges that land on Lumen PoPs), and their roles -- every regional PoP
    is transit-only (``roadm``) so it is never picked as a core or
    aggregation unless explicitly forced.
    """
    regional_nodes = load_regional_nodes(node_path)
    combined = lumen_pops + regional_nodes
    edges: dict[tuple[str, str], PhysicalEdge] = {}
    for edge_path in edge_paths:
        edges.update(load_carrier_edges(edge_path, combined))
    roles = {node.id: "roadm" for node in regional_nodes}
    return regional_nodes, edges, roles

def load_pop_roles(path: Path | None, carrier_pops: list[Node]) -> dict[str, str]:
    """Load optional Carrier PoP roles, defaulting every PoP to aggregator."""
    roles = {pop.id: "aggregator" for pop in carrier_pops}
    if path is None or not path.exists():
        return roles

    by_name = {pop.name.lower(): pop for pop in carrier_pops}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = row["name"].strip().lower()
            role = row["role"].strip().lower()
            if name not in by_name:
                raise ValueError(f"PoP role file references unknown Carrier PoP: {row['name']}")
            roles[by_name[name].id] = role
    return roles

def load_carrier_edges(path: Path, carrier_pops: list[Node]) -> dict[tuple[str, str], PhysicalEdge]:
    """Load the physical Carrier edge graph from the mapbook-derived CSV."""
    if not path.exists():
        raise ValueError(f"Carrier edge file does not exist: {path}")

    by_name = {pop.name.lower(): pop for pop in carrier_pops}
    edges: dict[tuple[str, str], PhysicalEdge] = {}

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source_name = row["source"].strip().lower()
            target_name = row["target"].strip().lower()
            if source_name not in by_name:
                raise ValueError(f"Edge file references unknown source PoP: {row['source']}")
            if target_name not in by_name:
                raise ValueError(f"Edge file references unknown target PoP: {row['target']}")

            source = by_name[source_name]
            target = by_name[target_name]
            key = edge_key(source.id, target.id)
            if row.get("distance_miles"):
                distance = float(row["distance_miles"])
            else:
                distance = haversine_miles(source, target)
            edges[key] = PhysicalEdge(
                source=key[0],
                target=key[1],
                distance_miles=distance,
                source_page=row.get("source_page", ""),
                note=row.get("note", ""),
            )

    return edges

def build_adjacency(
    edges: dict[tuple[str, str], PhysicalEdge],
) -> dict[str, list[tuple[str, float]]]:
    """Build a sorted weighted adjacency map from the physical edges."""
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for (left, right), edge in edges.items():
        adjacency.setdefault(left, []).append((right, edge.distance_miles))
        adjacency.setdefault(right, []).append((left, edge.distance_miles))
    for neighbors in adjacency.values():
        neighbors.sort()
    return adjacency
