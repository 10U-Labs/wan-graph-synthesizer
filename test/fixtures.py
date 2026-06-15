"""Shared test fixtures: vertex factories, a sample CSV, and a ring graph.

Centralized so unit, integration, and e2e tests reuse identical inputs without
duplicating data (which copy-paste detection would otherwise flag).
"""

from __future__ import annotations

from pathlib import Path

from wan_designer.model import (
    DesignArtifacts,
    DesignParams,
    Vertex,
    PhysicalEdge,
    SourceFiles,
    carrier_role,
    edge_key,
    is_carrier_pop,
)
from wan_designer.optimize import apply_role_overrides, optimize_three_tier_design
from wan_designer.validation import validate_design

# A four-vertex sample: two Lumen carrier PoPs plus two access sites, in the
# merged vertices schema (name,latitude,longitude,tenant,kind,shown_in_map,description).
SAMPLE_VERTICES_CSV = (
    "name,latitude,longitude,tenant,kind,shown_in_map,description\n"
    "Loose Site,39.0,-90.0,F-35,Military installation,Shown in map,\n"
    '"Denver, CO",39.7392,-104.9903,Lumen,PoP,Not shown in map,a Lumen PoP\n'
    '"Kansas City, MO",39.0997,-94.5786,Lumen,PoP,Not shown in map,\n'
    "Buckley,39.7,-104.75,F-35,Military installation,Shown in map,\n"
)

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


def carrier_pop(vertex_id: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build a Lumen carrier PoP vertex (a backbone PoP, not shown on the map)."""
    return Vertex(
        id=vertex_id,
        name=vertex_id,
        tenant="Lumen",
        kind="PoP",
        coords=(lat, lon),
        shown_in_map=False,
    )


def access_vertex(vertex_id: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build an access (F-35 installation) vertex."""
    return Vertex(
        id=vertex_id, name=vertex_id, tenant="F-35", kind="Military installation", coords=(lat, lon)
    )


def ring_vertices() -> list[Vertex]:
    """Build the six-PoP ring, a degree-one spur, and three access vertices."""
    pops = [carrier_pop(n, lat, lon) for n, (lat, lon) in RING_COORDS.items()]
    pops += [carrier_pop(n, lat, lon) for n, (lat, lon) in SPUR_COORDS.items()]
    access = [access_vertex(n, lat, lon) for n, (lat, lon) in ACCESS_COORDS.items()]
    return pops + access


def ring_physical_edges(distance: float = 100.0) -> dict[tuple[str, str], PhysicalEdge]:
    """Build the ring's physical edges with a uniform distance."""
    edges: dict[tuple[str, str], PhysicalEdge] = {}
    for left, right in RING_EDGE_PAIRS:
        key = edge_key(left, right)
        edges[key] = PhysicalEdge(source=key[0], target=key[1], distance_miles=distance)
    return edges


def write_sample_inputs(directory: Path) -> tuple[Path, Path]:
    """Write the sample vertices and edge CSVs into a directory; return their paths."""
    vertices_path = directory / "vertices.csv"
    vertices_path.write_text(SAMPLE_VERTICES_CSV, encoding="utf-8")
    edges_path = directory / "edges.csv"
    edges_path.write_text(SAMPLE_EDGES_CSV, encoding="utf-8")
    return vertices_path, edges_path


def _vertex_row(name: str, coords: tuple[float, float], tenant: str, kind: str, shown: str) -> str:
    """Render one vertices-CSV row."""
    lat, lon = coords
    return f"{name},{lat},{lon},{tenant},{kind},{shown},"


def solvable_vertices_csv() -> str:
    """Render a vertices CSV whose ring graph the optimizer can actually solve."""
    pops = "\n".join(
        _vertex_row(n, coords, "Lumen", "PoP", "Not shown in map")
        for n, coords in {**RING_COORDS, **SPUR_COORDS}.items()
    )
    access = "\n".join(
        _vertex_row(n, coords, "F-35", "Military installation", "Shown in map")
        for n, coords in ACCESS_COORDS.items()
    )
    header = "name,latitude,longitude,tenant,kind,shown_in_map,description\n"
    return f"{header}{pops}\n{access}\n"


def solvable_edges_csv() -> str:
    """Render the ring edge CSV matching the solvable vertices."""
    rows = "\n".join(f"{left},{right},100" for left, right in RING_EDGE_PAIRS)
    return f"source,target,distance_miles\n{rows}\n"


def write_solvable_inputs(directory: Path) -> tuple[Path, Path]:
    """Write a solvable vertices and edge CSV into a directory; return their paths."""
    vertices_path = directory / "vertices.csv"
    vertices_path.write_text(solvable_vertices_csv(), encoding="utf-8")
    edges_path = directory / "ring_edges.csv"
    edges_path.write_text(solvable_edges_csv(), encoding="utf-8")
    return vertices_path, edges_path


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
    vertices: Path,
    edges: Path,
    output: Path,
    extra: list[str] | None = None,
) -> list[str]:
    """Assemble argv for the design CLI."""
    args = [
        str(vertices),
        "--carrier-edges",
        str(edges),
        "--output-dir",
        str(output),
        # No regional carriers in the ring fixture: pass an empty --regional-edges
        # so the default config's regional edge files are not loaded.
        "--regional-edges",
    ]
    return args + (extra or [])


def ring_params() -> DesignParams:
    """Design parameters that solve the ring with a two-core tier."""
    return DesignParams(core_count=2)


def _ring_inputs() -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge], dict[str, str]]:
    """The ring vertices, physical edges, and default all-aggregator carrier roles."""
    vertices = ring_vertices()
    edges = ring_physical_edges()
    roles = {vertex.id: carrier_role(vertex) for vertex in vertices if is_carrier_pop(vertex)}
    return vertices, edges, roles


def ring_artifacts() -> DesignArtifacts:
    """Run the optimizer over the in-memory ring and bundle the artifacts."""
    vertices, edges, roles = _ring_inputs()
    design = optimize_three_tier_design(vertices, edges, roles, ring_params())
    return DesignArtifacts(vertices, edges, design, validate_design(vertices, design))


def _forced_artifacts(params: DesignParams) -> DesignArtifacts:
    """Run the ring optimizer with operator pins resolved through the CLI's path.

    Resolving via ``apply_role_overrides`` -- the same step ``run_design`` takes --
    means the artifacts reflect genuinely honored force-core/force-aggregation
    requests rather than emergent selections.
    """
    vertices, edges, roles = _ring_inputs()
    vertices, edges, overrides = apply_role_overrides(vertices, edges, params)
    design = optimize_three_tier_design(vertices, edges, roles, params, overrides)
    return DesignArtifacts(vertices, edges, design, validate_design(vertices, design))


def forced_aggregation_artifacts(name: str) -> DesignArtifacts:
    """Ring artifacts with one PoP forced onto the aggregation tier."""
    return _forced_artifacts(DesignParams(core_count=2, forced_aggregation_names=(name,)))


def forced_core_artifacts(name: str) -> DesignArtifacts:
    """Ring artifacts with one PoP forced onto the core tier."""
    return _forced_artifacts(DesignParams(core_count=2, forced_core_names=(name,)))


def sample_sources() -> SourceFiles:
    """Provenance paths for output rendering tests."""
    return SourceFiles(Path("vertices.csv"), Path("edges.csv"), None)
