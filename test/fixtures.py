"""Shared test fixtures: vertex factories, a sample CSV, and a ring graph.

Centralized so unit, integration, and e2e tests reuse identical inputs without
duplicating data (which copy-paste detection would otherwise flag).
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi.testclient import TestClient

from wan_designer.model import (
    DesignArtifacts,
    DesignParams,
    Vertex,
    PhysicalEdge,
    SourceFiles,
    carrier_role,
    edge_key,
    is_carrier_pop,
    slugify,
)
from wan_designer.optimize import apply_role_overrides, optimize_three_tier_design
from wan_designer.validation import validate_design

from api.app import build_app

VERTEX_HEADER = ["name", "latitude", "longitude", "kind", "shown_in_map", "description"]

# A four-vertex sample keyed by tenant: two Lumen carrier PoPs plus two F-35
# installations. Rows are (name, lat, lon, kind, shown_in_map, description).
SAMPLE_TENANT_ROWS: dict[str, list[tuple[str, float, float, str, str, str]]] = {
    "Lumen": [
        ("Denver, CO", 39.7392, -104.9903, "PoP", "Not shown in map", "a Lumen PoP"),
        ("Kansas City, MO", 39.0997, -94.5786, "PoP", "Not shown in map", ""),
    ],
    "F-35": [
        ("Loose Site", 39.0, -90.0, "Military installation", "Shown in map", ""),
        ("Buckley", 39.7, -104.75, "Military installation", "Shown in map", ""),
    ],
}

SAMPLE_EDGES_CSV = 'source,target,source_page,note\n"Denver, CO","Kansas City, MO",p,r\n'


def write_vertex_files(
    directory: Path, tenant_rows: dict[str, list[tuple[str, float, float, str, str, str]]]
) -> tuple[tuple[str, Path], ...]:
    """Write one per-tenant vertices CSV per tenant; return sorted (tenant, path) pairs."""
    files: list[tuple[str, Path]] = []
    for tenant, rows in tenant_rows.items():
        path = directory / f"{slugify(tenant)}.csv"
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(VERTEX_HEADER)
        writer.writerows(rows)
        path.write_text(buffer.getvalue(), encoding="utf-8")
        files.append((tenant, path))
    return tuple(sorted(files))

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


def write_sample_inputs(directory: Path) -> tuple[tuple[tuple[str, Path], ...], Path]:
    """Write the per-tenant sample vertices and edge CSVs; return their paths."""
    vertex_files = write_vertex_files(directory, SAMPLE_TENANT_ROWS)
    edges_path = directory / "edges.csv"
    edges_path.write_text(SAMPLE_EDGES_CSV, encoding="utf-8")
    return vertex_files, edges_path


def solvable_tenant_rows() -> dict[str, list[tuple[str, float, float, str, str, str]]]:
    """The ring's vertices keyed by tenant: Lumen PoPs and F-35 installations."""
    pops = [
        (n, lat, lon, "PoP", "Not shown in map", "")
        for n, (lat, lon) in {**RING_COORDS, **SPUR_COORDS}.items()
    ]
    access = [
        (n, lat, lon, "Military installation", "Shown in map", "")
        for n, (lat, lon) in ACCESS_COORDS.items()
    ]
    return {"Lumen": pops, "F-35": access}


def solvable_edges_csv() -> str:
    """Render the ring edge CSV matching the solvable vertices."""
    rows = "\n".join(f"{left},{right},100" for left, right in RING_EDGE_PAIRS)
    return f"source,target,distance_miles\n{rows}\n"


def write_solvable_inputs(directory: Path) -> tuple[tuple[tuple[str, Path], ...], Path]:
    """Write the solvable per-tenant vertices and edge CSVs; return their paths."""
    vertex_files = write_vertex_files(directory, solvable_tenant_rows())
    edges_path = directory / "ring_edges.csv"
    edges_path.write_text(solvable_edges_csv(), encoding="utf-8")
    return vertex_files, edges_path


def write_solvable_config(directory: Path, min_core_count: int | None = None) -> Path:
    """Write a config naming the solvable per-tenant vertices and edges; return its path."""
    vertex_files, edges_path = write_solvable_inputs(directory)
    lines = []
    if min_core_count is not None:
        lines += ["design:", f"  min_core_count: {min_core_count}"]
    lines += [
        "inputs:",
        f"  carrier_edges: {edges_path}",
        "  regional_edges: []",
        "  vertices:",
    ]
    lines += [f"    {tenant}: {path}" for tenant, path in vertex_files]
    lines.append(f"output_dir: {directory / 'out'}")
    config_path = directory / "joint.yml"
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return config_path


def physical_edges_from(
    pairs: dict[tuple[str, str], float],
) -> dict[tuple[str, str], PhysicalEdge]:
    """Build a physical edge map from a {(left, right): distance} mapping."""
    edges: dict[tuple[str, str], PhysicalEdge] = {}
    for (left, right), dist in pairs.items():
        key = edge_key(left, right)
        edges[key] = PhysicalEdge(source=key[0], target=key[1], distance_miles=dist)
    return edges


def ring_params() -> DesignParams:
    """Design parameters that solve the ring with a two-core tier."""
    return DesignParams(min_core_count=2)


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
    return _forced_artifacts(DesignParams(min_core_count=2, forced_aggregation_names=(name,)))


def forced_core_artifacts(name: str) -> DesignArtifacts:
    """Ring artifacts with one PoP forced onto the core tier."""
    return _forced_artifacts(DesignParams(min_core_count=2, forced_core_names=(name,)))


def sample_sources() -> SourceFiles:
    """Provenance paths for output rendering tests."""
    return SourceFiles((Path("vertices/lumen.csv"),), Path("edges.csv"), None)


def api_client(directory: Path) -> TestClient:
    """Build a TestClient over the app: a solvable 'joint' config plus a static UI."""
    write_solvable_config(directory, min_core_count=2)
    static_dir = directory / "www"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    return TestClient(build_app(directory, static_dir))
