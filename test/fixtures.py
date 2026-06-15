"""Shared test fixtures: node factories, a sample KML/CSV, and a ring graph.

Centralized so unit, integration, and e2e tests reuse identical inputs without
duplicating data (which copy-paste detection would otherwise flag).
"""

from __future__ import annotations

from pathlib import Path

from wan_designer.model import (
    DesignArtifacts,
    DesignParams,
    Node,
    PhysicalEdge,
    SourceFiles,
    edge_key,
)
from wan_designer.optimize import apply_role_overrides, optimize_three_tier_design
from wan_designer.validation import validate_design

SAMPLE_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Top</name>
    <Placemark>
      <name>Loose Site</name>
      <Point><coordinates>-90.0,39.0,0</coordinates></Point>
    </Placemark>
    <Placemark>
      <name>Ghost</name>
    </Placemark>
    <Folder>
      <name>Carrier 400G PoPs</name>
      <Placemark>
        <name>Denver, CO</name>
        <description>Carrier 400G PoP</description>
        <Point><coordinates>-104.9903,39.7392,0</coordinates></Point>
      </Placemark>
      <Placemark>
        <name>Kansas City, MO</name>
        <Point><coordinates>-94.5786,39.0997,0</coordinates></Point>
      </Placemark>
      <Placemark>
        <name>No Geometry</name>
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

SAMPLE_EDGES_CSV = 'source,target,source_page,note\n"Denver, CO","Kansas City, MO",p,r\n'

RING_COORDS = {
    "P0": (40.0, -100.0),
    "P1": (41.0, -100.0),
    "P2": (41.5, -99.0),
    "P3": (41.0, -98.0),
    "P4": (40.0, -98.0),
    "P5": (39.5, -99.0),
}
SPUR_COORDS = {"P6": (37.0, -100.0)}
ACCESS_COORDS = {"A1": (41.0, -99.9), "A2": (40.0, -98.1), "A3": (41.4, -99.1)}
RING_EDGE_PAIRS = [
    ("P0", "P1"),
    ("P1", "P2"),
    ("P2", "P3"),
    ("P3", "P4"),
    ("P4", "P5"),
    ("P5", "P0"),
    ("P0", "P6"),
]


def carrier_pop(node_id: str, lat: float = 0.0, lon: float = 0.0) -> Node:
    """Build a carrier PoP node."""
    return Node(
        id=node_id,
        name=node_id,
        category="Carrier 400G PoPs",
        kind="carrier_pop",
        lat=lat,
        lon=lon,
    )


def access_node(node_id: str, lat: float = 0.0, lon: float = 0.0) -> Node:
    """Build an access (F-35) node."""
    return Node(id=node_id, name=node_id, category="F-35", kind="f35", lat=lat, lon=lon)


def ring_nodes() -> list[Node]:
    """Build the six-PoP ring, a degree-one spur, and three access nodes."""
    pops = [carrier_pop(n, lat, lon) for n, (lat, lon) in RING_COORDS.items()]
    pops += [carrier_pop(n, lat, lon) for n, (lat, lon) in SPUR_COORDS.items()]
    access = [access_node(n, lat, lon) for n, (lat, lon) in ACCESS_COORDS.items()]
    return pops + access


def ring_physical_edges(distance: float = 100.0) -> dict[tuple[str, str], PhysicalEdge]:
    """Build the ring's physical edges with a uniform distance."""
    edges: dict[tuple[str, str], PhysicalEdge] = {}
    for left, right in RING_EDGE_PAIRS:
        key = edge_key(left, right)
        edges[key] = PhysicalEdge(source=key[0], target=key[1], distance_miles=distance)
    return edges


def write_sample_inputs(directory: Path) -> tuple[Path, Path]:
    """Write the sample KML and edge CSV into a directory; return their paths."""
    kml_path = directory / "doc.kml"
    kml_path.write_text(SAMPLE_KML, encoding="utf-8")
    edges_path = directory / "edges.csv"
    edges_path.write_text(SAMPLE_EDGES_CSV, encoding="utf-8")
    return kml_path, edges_path


def _placemark(name: str, lat: float, lon: float) -> str:
    """Render one point placemark."""
    return (
        f"      <Placemark><name>{name}</name>"
        f"<Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>"
    )


def solvable_kml() -> str:
    """Render a KML whose ring graph the optimizer can actually solve."""
    pops = "\n".join(
        _placemark(n, lat, lon)
        for n, (lat, lon) in {**RING_COORDS, **SPUR_COORDS}.items()
    )
    access = "\n".join(_placemark(n, lat, lon) for n, (lat, lon) in ACCESS_COORDS.items())
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Net</name>\n'
        f"<Folder><name>Carrier 400G PoPs</name>\n{pops}\n</Folder>\n"
        f"<Folder><name>F-35 CONUS Installations</name>\n{access}\n</Folder>\n"
        "</Document></kml>\n"
    )


def solvable_edges_csv() -> str:
    """Render the ring edge CSV matching the solvable KML."""
    rows = "\n".join(f"{left},{right},100" for left, right in RING_EDGE_PAIRS)
    return f"source,target,distance_miles\n{rows}\n"


def write_solvable_inputs(directory: Path) -> tuple[Path, Path]:
    """Write a solvable KML and edge CSV into a directory; return their paths."""
    kml_path = directory / "net.kml"
    kml_path.write_text(solvable_kml(), encoding="utf-8")
    edges_path = directory / "ring_edges.csv"
    edges_path.write_text(solvable_edges_csv(), encoding="utf-8")
    return kml_path, edges_path


def physical_edges_from(
    pairs: dict[tuple[str, str], float],
) -> dict[tuple[str, str], PhysicalEdge]:
    """Build a physical edge map from a {(left, right): distance} mapping."""
    edges: dict[tuple[str, str], PhysicalEdge] = {}
    for (left, right), dist in pairs.items():
        key = edge_key(left, right)
        edges[key] = PhysicalEdge(source=key[0], target=key[1], distance_miles=dist)
    return edges


def design_args(
    kml: Path,
    edges: Path,
    output: Path,
    roles: str = "",
    extra: list[str] | None = None,
) -> list[str]:
    """Assemble argv for the design CLI."""
    args = [
        str(kml),
        "--carrier-edges",
        str(edges),
        "--pop-roles",
        roles,
        "--output-dir",
        str(output),
        "--regional-nodes",
        "",
    ]
    return args + (extra or [])


def ring_params() -> DesignParams:
    """Design parameters that solve the ring with a two-core tier."""
    return DesignParams(core_count=2)


def _ring_inputs() -> tuple[list[Node], dict[tuple[str, str], PhysicalEdge], dict[str, str]]:
    """The ring nodes, physical edges, and default all-aggregator carrier roles."""
    nodes = ring_nodes()
    edges = ring_physical_edges()
    roles = {node.id: "aggregator" for node in nodes if node.kind == "carrier_pop"}
    return nodes, edges, roles


def ring_artifacts() -> DesignArtifacts:
    """Run the optimizer over the in-memory ring and bundle the artifacts."""
    nodes, edges, roles = _ring_inputs()
    design = optimize_three_tier_design(nodes, edges, roles, ring_params())
    return DesignArtifacts(nodes, edges, design, validate_design(nodes, design))


def _forced_artifacts(params: DesignParams) -> DesignArtifacts:
    """Run the ring optimizer with operator pins resolved through the CLI's path.

    Resolving via ``apply_role_overrides`` -- the same step ``run_design`` takes --
    means the artifacts reflect genuinely honored force-core/force-aggregation
    requests rather than emergent selections.
    """
    nodes, edges, roles = _ring_inputs()
    nodes, edges, overrides = apply_role_overrides(nodes, edges, params)
    design = optimize_three_tier_design(nodes, edges, roles, params, overrides)
    return DesignArtifacts(nodes, edges, design, validate_design(nodes, design))


def forced_aggregation_artifacts(name: str) -> DesignArtifacts:
    """Ring artifacts with one PoP forced onto the aggregation tier."""
    return _forced_artifacts(DesignParams(core_count=2, forced_aggregation_names=(name,)))


def forced_core_artifacts(name: str) -> DesignArtifacts:
    """Ring artifacts with one PoP forced onto the core tier."""
    return _forced_artifacts(DesignParams(core_count=2, forced_core_names=(name,)))


def sample_sources() -> SourceFiles:
    """Provenance paths for output rendering tests."""
    return SourceFiles(Path("input.kml"), Path("edges.csv"), None)
