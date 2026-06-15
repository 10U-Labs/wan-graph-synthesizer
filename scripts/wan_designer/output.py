"""Render a design as JSON, CSV, KML, and Graphviz DOT."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree as ET

from wan_designer.model import (
    KML_NS,
    Design,
    DesignArtifacts,
    Vertex,
    SourceFiles,
    edge_key,
    is_carrier_pop,
)
from wan_designer.validation import included_vertex_ids, vertex_role


def sorted_physical_edges(design: Design) -> list[tuple[str, str]]:
    """Return the design's physical edge keys in sorted order."""
    return sorted(design.physical_edge_keys)

def write_json(
    output_path: Path,
    sources: SourceFiles,
    artifacts: DesignArtifacts,
) -> None:
    """Write the full design, vertices, edges, and validation report as JSON."""
    vertices = artifacts.vertices
    physical_edges = artifacts.physical_edges
    design = artifacts.design
    validation = artifacts.validation
    vertices_by_id = {vertex.id: vertex for vertex in vertices}
    payload = {
        "vertices_files": [str(path) for path in sources.vertex_files],
        "physical_edge_file": str(sources.edge_path),
        "mapbook_pdf": str(sources.mapbook_pdf) if sources.mapbook_pdf else None,
        "objective": (
            "Three-tier WAN design: access vertices dual-home to Carrier aggregation PoPs, "
            "aggregation PoPs dual-home to core PoPs over the physical Carrier graph, "
            "and the core tier uses at least three strong vertices, with extra cores "
            "added where they bring demand closer."
        ),
        "summary": {
            "core_count": len(design.core_ids),
            "aggregation_count": len(design.aggregation_ids),
            "transit_count": len(design.transit_ids),
            "access_vertex_count": sum(1 for vertex in vertices if not is_carrier_pop(vertex)),
            "access_edge_count": len(design.access_edges),
            "physical_edge_count": len(design.physical_edge_keys),
            "access_miles": round(design.metrics.access_miles, 3),
            "physical_carrier_miles": round(design.metrics.physical_miles, 3),
            "total_design_miles": round(
                design.metrics.access_miles + design.metrics.physical_miles, 3
            ),
            "score": round(design.metrics.score, 3),
            "cores": [vertices_by_id[vertex_id].name for vertex_id in design.core_ids],
            "aggregations": [
                vertices_by_id[vertex_id].name for vertex_id in design.aggregation_ids
            ],
        },
        "validation": validation,
        "vertices": [
            {
                **asdict(vertex),
                "tier_role": vertex_role(vertex.id, design, vertex),
                "included": vertex.id in included_vertex_ids(design),
            }
            for vertex in vertices
        ],
        "access_edges": [
            {
                "source_id": edge.source,
                "source_name": vertices_by_id[edge.source].name,
                "target_id": edge.target,
                "target_name": vertices_by_id[edge.target].name,
                "edge_kind": "access_to_aggregation",
                "distance_miles": round(edge.distance_miles, 3),
            }
            for edge in sorted(design.access_edges, key=lambda item: (item.source, item.target))
        ],
        "physical_edges": [
            {
                "source_id": left,
                "source_name": vertices_by_id[left].name,
                "target_id": right,
                "target_name": vertices_by_id[right].name,
                "edge_kind": "carrier_physical",
                "distance_miles": round(physical_edges[edge_key(left, right)].distance_miles, 3),
                "source_page": physical_edges[edge_key(left, right)].source_page,
                "note": physical_edges[edge_key(left, right)].note,
            }
            for left, right in sorted_physical_edges(design)
        ],
        "path_uses": [
            {
                "purpose": path_use.purpose,
                "source_id": path_use.source,
                "source_name": vertices_by_id[path_use.source].name,
                "target_id": path_use.target,
                "target_name": vertices_by_id[path_use.target].name,
                "distance_miles": round(path_use.distance_miles, 3),
                "path": [vertices_by_id[vertex_id].name for vertex_id in path_use.path],
            }
            for path_use in design.path_uses
        ],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

CSV_FIELDNAMES = [
    "source_id",
    "source_name",
    "source_role",
    "target_id",
    "target_name",
    "target_role",
    "edge_kind",
    "distance_miles",
    "source_page",
]

def csv_edge_row(
    design: Design, source: Vertex, target: Vertex, meta: tuple[str, float, str]
) -> dict[str, object]:
    """Build one CSV row for an edge between two vertices."""
    edge_kind, distance, source_page = meta
    return {
        "source_id": source.id,
        "source_name": source.name,
        "source_role": vertex_role(source.id, design, source),
        "target_id": target.id,
        "target_name": target.name,
        "target_role": vertex_role(target.id, design, target),
        "edge_kind": edge_kind,
        "distance_miles": round(distance, 3),
        "source_page": source_page,
    }

def write_csv(output_path: Path, artifacts: DesignArtifacts) -> None:
    """Write all selected edges with vertex roles and distances as CSV."""
    physical_edges = artifacts.physical_edges
    design = artifacts.design
    vertices_by_id = {vertex.id: vertex for vertex in artifacts.vertices}
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for edge in sorted(design.access_edges, key=lambda item: (item.source, item.target)):
            meta = ("access_to_aggregation", edge.distance_miles, "")
            row = csv_edge_row(
                design, vertices_by_id[edge.source], vertices_by_id[edge.target], meta
            )
            writer.writerow(row)
        for left, right in sorted_physical_edges(design):
            physical_edge = physical_edges[edge_key(left, right)]
            meta = ("carrier_physical", physical_edge.distance_miles, physical_edge.source_page)
            row = csv_edge_row(design, vertices_by_id[left], vertices_by_id[right], meta)
            writer.writerow(row)

# (layer key, folder name, paddle icon color slug, icon scale). We use Google's
# pre-colored paddle icons rather than tinting a white icon with IconStyle
# <color>, because many viewers (Google My Maps, QGIS, web) ignore that tint and
# render every tier identically. Slugs map to mapfiles/kml/paddle/<slug>-blank.png:
# blue access, purple aggregation, red core, orange secret regions, green CUI
# regions, yellow Top Secret regions.
LAYER_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("access", "Access Vertices", "blu", "0.85"),
    ("aggregation", "Aggregation Points", "purple", "0.9"),
    ("core", "Core Vertices", "red", "1.1"),
    ("secret_east", "Secret East Regions", "orange", "0.95"),
    ("secret_west", "Secret West Regions", "orange", "0.95"),
    ("cui_east", "CUI East Regions", "grn", "0.95"),
    ("cui_west", "CUI West Regions", "grn", "0.95"),
    ("ts_east", "Top Secret East Regions", "ylw", "0.95"),
    ("ts_west", "Top Secret West Regions", "ylw", "0.95"),
)

# CSP-data-center vertices are classified into Secret/CUI/Top Secret families by
# name (checked most-specific first so "Top Secret" is not caught by "Secret"),
# then split east/west by an "east"/"west" hint; a region with neither hint is
# omitted from the map.
REGION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("top secret", "ts"),
    ("cui", "cui"),
    ("secret", "secret"),
)
CSP_KIND = "CSP data center"

def region_layer(name: str) -> str | None:
    """Map a CSP region's name to its ``<family>_<east|west>`` layer, or None."""
    lowered = name.lower()
    prefix = next((p for keyword, p in REGION_PREFIXES if keyword in lowered), None)
    if prefix is None:
        return None
    if "east" in lowered:
        return f"{prefix}_east"
    if "west" in lowered:
        return f"{prefix}_west"
    return None

def kml_layer_for_vertex(vertex: Vertex, role: str) -> str | None:
    """Map a vertex to one of the output layers, or None to omit it."""
    if vertex.kind == CSP_KIND:
        return region_layer(vertex.name)
    if role in ("access", "aggregation", "core"):
        return role
    return None

def write_kml_styles(document: ET.Element) -> None:
    """Append vertex and edge style definitions to the KML document."""
    base = "https://maps.google.com/mapfiles/kml/paddle"
    for key, _name, slug, scale in LAYER_SPECS:
        style = ET.SubElement(document, "Style", id=f"vertex_{key}")
        icon_style = ET.SubElement(style, "IconStyle")
        # No <color>: the paddle icon is already the right color, and tinting it
        # would only darken it in the viewers that honor IconStyle <color>.
        ET.SubElement(icon_style, "scale").text = scale
        ET.SubElement(ET.SubElement(icon_style, "Icon"), "href").text = f"{base}/{slug}-blank.png"
    # Edges stay neutral gray so the tier palette reads on the vertex icons alone.
    for edge_kind, color, width in (("access", "ff9e9e9e", "1.2"), ("backbone", "ff5a5a5a", "2.0")):
        style = ET.SubElement(document, "Style", id=f"edge_{edge_kind}")
        line_style = ET.SubElement(style, "LineStyle")
        ET.SubElement(line_style, "color").text = color
        ET.SubElement(line_style, "width").text = width

def add_kml_line(folder: ET.Element, label: str, style: str, desc: str, ends: str) -> None:
    """Append one styled line-string placemark to a KML folder."""
    placemark = ET.SubElement(folder, "Placemark")
    ET.SubElement(placemark, "name").text = label
    ET.SubElement(placemark, "styleUrl").text = style
    ET.SubElement(placemark, "description").text = desc
    line = ET.SubElement(placemark, "LineString")
    ET.SubElement(line, "tessellate").text = "1"
    ET.SubElement(line, "coordinates").text = ends

def write_kml_vertices(
    folder: ET.Element, design: Design, vertices: list[Vertex], layer_key: str
) -> None:
    """Append a placemark for every included vertex in one output layer."""
    included = included_vertex_ids(design)
    members = [
        vertex
        for vertex in vertices
        if vertex.id in included
        and kml_layer_for_vertex(vertex, vertex_role(vertex.id, design, vertex)) == layer_key
    ]
    for vertex in sorted(members, key=lambda item: item.name):
        placemark = ET.SubElement(folder, "Placemark")
        ET.SubElement(placemark, "name").text = vertex.name
        ET.SubElement(placemark, "styleUrl").text = f"#vertex_{layer_key}"
        ET.SubElement(placemark, "description").text = f"{vertex.tenant}\n{vertex.id}"
        point = ET.SubElement(placemark, "Point")
        ET.SubElement(point, "coordinates").text = f"{vertex.lon},{vertex.lat},0"

def kml_edge_specs(artifacts: DesignArtifacts) -> list[tuple[str, str, str, str]]:
    """List (source_id, target_id, style, description) for every logical edge.

    Backbone links are drawn end-to-end between aggregation and core PoPs,
    skipping the intermediate Carrier PoPs each routed path passes through.
    """
    design = artifacts.design
    specs: list[tuple[str, str, str, str]] = []
    for edge in sorted(design.access_edges, key=lambda item: (item.source, item.target)):
        desc = f"access_to_aggregation\n{edge.distance_miles:.1f} miles"
        specs.append((edge.source, edge.target, "#edge_access", desc))
    for use in sorted(design.path_uses, key=lambda item: (item.source, item.target)):
        desc = f"{use.purpose}\n{use.distance_miles:.1f} miles"
        specs.append((use.source, use.target, "#edge_backbone", desc))
    return specs

def write_kml_edges(folder: ET.Element, artifacts: DesignArtifacts) -> None:
    """Append a placemark for every selected access and physical edge."""
    vertices_by_id = {vertex.id: vertex for vertex in artifacts.vertices}
    for source_id, target_id, style, desc in kml_edge_specs(artifacts):
        source, target = vertices_by_id[source_id], vertices_by_id[target_id]
        ends = f"{source.lon},{source.lat},0 {target.lon},{target.lat},0"
        add_kml_line(folder, f"{source.name} to {target.name}", style, desc, ends)

def write_kml(output_path: Path, artifacts: DesignArtifacts) -> None:
    """Write the design as a KML map with one folder per tier layer."""
    kml = ET.Element("kml", xmlns=KML_NS["k"])
    document = ET.SubElement(kml, "Document")
    ET.SubElement(document, "name").text = "Three-Tier Carrier WAN Design"
    write_kml_styles(document)

    for key, name, _color, _scale in LAYER_SPECS:
        folder = ET.SubElement(document, "Folder")
        ET.SubElement(folder, "name").text = name
        write_kml_vertices(folder, artifacts.design, artifacts.vertices, key)

    edge_folder = ET.SubElement(document, "Folder")
    ET.SubElement(edge_folder, "name").text = "Edges"
    write_kml_edges(edge_folder, artifacts)

    ET.indent(kml, space="  ")
    ET.ElementTree(kml).write(output_path, encoding="utf-8", xml_declaration=True)

def dot_escape(value: str) -> str:
    """Escape a label for safe inclusion in a Graphviz DOT string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')

def write_dot(output_path: Path, artifacts: DesignArtifacts) -> None:
    """Write the design as a Graphviz DOT graph colored by tier role."""
    vertices = artifacts.vertices
    physical_edges = artifacts.physical_edges
    design = artifacts.design
    colors = {
        "access": "#f9a825",
        "aggregation": "#00897b",
        "core": "#c62828",
        "transit": "#757575",
    }
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("graph three_tier_carrier_wan_design {\n")
        handle.write('  graph [overlap=false, splines=true];\n')
        handle.write('  vertex [shape=circle, style=filled, fontname="Helvetica", fontsize=9];\n')
        handle.write('  edge [fontname="Helvetica", fontsize=8];\n')
        included = included_vertex_ids(design)
        for vertex in sorted(
            (vertex for vertex in vertices if vertex.id in included), key=lambda item: item.id
        ):
            role = vertex_role(vertex.id, design, vertex)
            handle.write(
                f'  "{vertex.id}" [label="{dot_escape(vertex.name)}", '
                f'fillcolor="{colors[role]}", fontcolor="white"];\n'
            )
        for edge in sorted(design.access_edges, key=lambda item: (item.source, item.target)):
            handle.write(
                f'  "{edge.source}" -- "{edge.target}" '
                f'[label="{edge.distance_miles:.0f} mi", color="#f9a825", penwidth=1.1];\n'
            )
        for left, right in sorted_physical_edges(design):
            physical_edge = physical_edges[edge_key(left, right)]
            handle.write(
                f'  "{left}" -- "{right}" '
                f'[label="{physical_edge.distance_miles:.0f} mi", color="#333333", penwidth=2.0];\n'
            )
        handle.write("}\n")

def write_outputs(
    output_dir: Path,
    sources: SourceFiles,
    artifacts: DesignArtifacts,
) -> dict[str, Path]:
    """Write JSON, CSV, KML, and DOT renderings of the design."""
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "json": output_dir / "network_design.json",
        "csv": output_dir / "network_edges.csv",
        "kml": output_dir / "network_design.kml",
        "dot": output_dir / "network_design.dot",
    }
    write_json(outputs["json"], sources, artifacts)
    write_csv(outputs["csv"], artifacts)
    write_kml(outputs["kml"], artifacts)
    write_dot(outputs["dot"], artifacts)
    return outputs
