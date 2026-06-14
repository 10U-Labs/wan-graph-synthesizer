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
    Node,
    SourceFiles,
    edge_key,
)
from wan_designer.validation import included_node_ids, node_role


def sorted_physical_edges(design: Design) -> list[tuple[str, str]]:
    """Return the design's physical edge keys in sorted order."""
    return sorted(design.physical_edge_keys)

def write_json(
    output_path: Path,
    sources: SourceFiles,
    artifacts: DesignArtifacts,
) -> None:
    """Write the full design, nodes, edges, and validation report as JSON."""
    nodes = artifacts.nodes
    physical_edges = artifacts.physical_edges
    design = artifacts.design
    validation = artifacts.validation
    nodes_by_id = {node.id: node for node in nodes}
    payload = {
        "input_file": str(sources.input_path),
        "physical_edge_file": str(sources.edge_path),
        "mapbook_pdf": str(sources.mapbook_pdf) if sources.mapbook_pdf else None,
        "objective": (
            "Three-tier WAN design: access nodes dual-home to Carrier aggregation PoPs, "
            "aggregation PoPs dual-home to core PoPs over the physical Carrier graph, "
            "and the core tier uses at least three strong nodes, with Salt Lake City "
            "required and extra cores added where they bring demand closer."
        ),
        "summary": {
            "core_count": len(design.core_ids),
            "aggregation_count": len(design.aggregation_ids),
            "transit_count": len(design.transit_ids),
            "access_node_count": sum(1 for node in nodes if node.kind != "carrier_pop"),
            "access_edge_count": len(design.access_edges),
            "physical_edge_count": len(design.physical_edge_keys),
            "access_miles": round(design.metrics.access_miles, 3),
            "physical_carrier_miles": round(design.metrics.physical_miles, 3),
            "total_design_miles": round(
                design.metrics.access_miles + design.metrics.physical_miles, 3
            ),
            "score": round(design.metrics.score, 3),
            "cores": [nodes_by_id[node_id].name for node_id in design.core_ids],
            "aggregations": [nodes_by_id[node_id].name for node_id in design.aggregation_ids],
        },
        "validation": validation,
        "nodes": [
            {
                **asdict(node),
                "tier_role": node_role(node.id, design, node),
                "included": node.id in included_node_ids(design),
            }
            for node in nodes
        ],
        "access_edges": [
            {
                "source_id": edge.source,
                "source_name": nodes_by_id[edge.source].name,
                "target_id": edge.target,
                "target_name": nodes_by_id[edge.target].name,
                "edge_kind": "access_to_aggregation",
                "distance_miles": round(edge.distance_miles, 3),
            }
            for edge in sorted(design.access_edges, key=lambda item: (item.source, item.target))
        ],
        "physical_edges": [
            {
                "source_id": left,
                "source_name": nodes_by_id[left].name,
                "target_id": right,
                "target_name": nodes_by_id[right].name,
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
                "source_name": nodes_by_id[path_use.source].name,
                "target_id": path_use.target,
                "target_name": nodes_by_id[path_use.target].name,
                "distance_miles": round(path_use.distance_miles, 3),
                "path": [nodes_by_id[node_id].name for node_id in path_use.path],
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
    design: Design, source: Node, target: Node, meta: tuple[str, float, str]
) -> dict[str, object]:
    """Build one CSV row for an edge between two nodes."""
    edge_kind, distance, source_page = meta
    return {
        "source_id": source.id,
        "source_name": source.name,
        "source_role": node_role(source.id, design, source),
        "target_id": target.id,
        "target_name": target.name,
        "target_role": node_role(target.id, design, target),
        "edge_kind": edge_kind,
        "distance_miles": round(distance, 3),
        "source_page": source_page,
    }

def write_csv(output_path: Path, artifacts: DesignArtifacts) -> None:
    """Write all selected edges with node roles and distances as CSV."""
    physical_edges = artifacts.physical_edges
    design = artifacts.design
    nodes_by_id = {node.id: node for node in artifacts.nodes}
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for edge in sorted(design.access_edges, key=lambda item: (item.source, item.target)):
            meta = ("access_to_aggregation", edge.distance_miles, "")
            row = csv_edge_row(design, nodes_by_id[edge.source], nodes_by_id[edge.target], meta)
            writer.writerow(row)
        for left, right in sorted_physical_edges(design):
            physical_edge = physical_edges[edge_key(left, right)]
            meta = ("carrier_physical", physical_edge.distance_miles, physical_edge.source_page)
            row = csv_edge_row(design, nodes_by_id[left], nodes_by_id[right], meta)
            writer.writerow(row)

# (layer key, folder name, icon ABGR color, icon scale). KML colors are
# aabbggrr: blue access, purple aggregation, red core, orange secret regions.
LAYER_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("access", "Access Nodes", "ffff0000", "0.85"),
    ("aggregation", "Aggregation Points", "ff800080", "0.9"),
    ("core", "Core Nodes", "ff0000ff", "1.1"),
    ("secret_east", "Secret East Regions", "ff00a5ff", "0.95"),
    ("secret_west", "Secret West Regions", "ff00a5ff", "0.95"),
)

def kml_layer_for_node(node: Node, role: str) -> str | None:
    """Map a node to one of the five output layers, or None to omit it."""
    if node.kind == "csp_secret":
        lowered = node.name.lower()
        if "east" in lowered:
            return "secret_east"
        if "west" in lowered:
            return "secret_west"
        return None
    if role in ("access", "aggregation", "core"):
        return role
    return None

def write_kml_styles(document: ET.Element) -> None:
    """Append node and edge style definitions to the KML document."""
    # A pure-white marker is required for IconStyle <color> to tint reliably.
    # The shapes/placemark_circle.png icon ignores the tint in Google My Maps,
    # QGIS, and most web viewers, so every tier rendered as one color there.
    marker = "https://maps.google.com/mapfiles/kml/paddle/wht-blank.png"
    for key, _name, color, scale in LAYER_SPECS:
        style = ET.SubElement(document, "Style", id=f"node_{key}")
        icon_style = ET.SubElement(style, "IconStyle")
        ET.SubElement(icon_style, "color").text = color
        ET.SubElement(icon_style, "scale").text = scale
        ET.SubElement(ET.SubElement(icon_style, "Icon"), "href").text = marker
    # Edges stay neutral gray so the tier palette reads on the node icons alone.
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

def write_kml_nodes(
    folder: ET.Element, design: Design, nodes: list[Node], layer_key: str
) -> None:
    """Append a placemark for every included node in one output layer."""
    included = included_node_ids(design)
    members = [
        node
        for node in nodes
        if node.id in included
        and kml_layer_for_node(node, node_role(node.id, design, node)) == layer_key
    ]
    for node in sorted(members, key=lambda item: item.name):
        placemark = ET.SubElement(folder, "Placemark")
        ET.SubElement(placemark, "name").text = node.name
        ET.SubElement(placemark, "styleUrl").text = f"#node_{layer_key}"
        ET.SubElement(placemark, "description").text = f"{node.category}\n{node.id}"
        point = ET.SubElement(placemark, "Point")
        ET.SubElement(point, "coordinates").text = f"{node.lon},{node.lat},0"

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
    nodes_by_id = {node.id: node for node in artifacts.nodes}
    for source_id, target_id, style, desc in kml_edge_specs(artifacts):
        source, target = nodes_by_id[source_id], nodes_by_id[target_id]
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
        write_kml_nodes(folder, artifacts.design, artifacts.nodes, key)

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
    nodes = artifacts.nodes
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
        handle.write('  node [shape=circle, style=filled, fontname="Helvetica", fontsize=9];\n')
        handle.write('  edge [fontname="Helvetica", fontsize=8];\n')
        included = included_node_ids(design)
        for node in sorted(
            (node for node in nodes if node.id in included), key=lambda item: item.id
        ):
            role = node_role(node.id, design, node)
            handle.write(
                f'  "{node.id}" [label="{dot_escape(node.name)}", '
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
