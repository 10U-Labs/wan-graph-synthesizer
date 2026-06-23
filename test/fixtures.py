"""Shared test fixtures: vertex factories, a sample CSV, and a ring graph.

Centralized so unit, integration, and e2e tests reuse identical inputs without
duplicating data (which copy-paste detection would otherwise flag).
"""

from __future__ import annotations

import csv
import dataclasses
import io
from collections.abc import Iterable, Sequence
from pathlib import Path

from seed import (
    OFF_NET_KIND,
    OFF_NET_TENANT,
    load_carrier_edges,
    load_off_net_sites,
    load_vertices,
    slugify,
)
from wan_graph.model import PhysicalEdge, Vertex, edge_key
from wan_synthesizer.model import (
    KIND_ROADM,
    DesignArtifacts,
    DesignParams,
    DesignPaths,
    ForcedConnection,
    RoleExclusions,
    SourceFiles,
    is_carrier_pop,
)
from wan_synthesizer.synthesize import synthesize_three_tier_design
from wan_synthesizer.overrides import apply_role_overrides, materialize_selected_colocation_twins
from wan_synthesizer.stages import dual_home, finalize
from wan_synthesizer.validation import validate_design

VERTEX_HEADER = ["name", "latitude", "longitude", "kind", "shown_in_map", "description"]


def _write_csv(path: Path, header: list[str], rows: Iterable[Sequence[object]]) -> None:
    """Write a header row and data rows to ``path`` as CSV."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")

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
        _write_csv(path, VERTEX_HEADER, rows)
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


def off_net_site(vertex_id: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build an off-net candidate site: not a carrier PoP and carrying no demand."""
    return Vertex(
        id=vertex_id, name=vertex_id, tenant=OFF_NET_TENANT, kind=OFF_NET_KIND, coords=(lat, lon)
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


def load_design_inputs(
    paths: DesignPaths,
) -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge]]:
    """Load vertices and carrier fiber from CSV paths.

    Lives in test support, not the shipped library: production reads the JSON
    substrate via ``load_input_graph``; only the suite drives a design from CSVs.
    """
    vertices = load_vertices(list(paths.vertex_files))
    if not vertices:
        raise ValueError("No vertices found in the configured vertex files")
    carrier_pops = [vertex for vertex in vertices if is_carrier_pop(vertex)]
    physical_edges: dict[tuple[str, str], PhysicalEdge] = {}
    for edge_path in (paths.edge_path, *paths.regional_edge_paths):
        physical_edges.update(load_carrier_edges(edge_path, carrier_pops))
    return vertices, physical_edges


def run_design(
    paths: DesignPaths,
    params: DesignParams,
    forced_connections: tuple[ForcedConnection, ...] = (),
    excluded_connections: tuple[ForcedConnection, ...] = (),
) -> DesignArtifacts:
    """Drive the whole pipeline from CSV paths -- the suite's design driver.

    Mirrors the steps the Fargate entrypoint runs inline (dual-home -> overrides ->
    synthesize -> finalize); kept in test support because no shipped code drives a
    design from raw files.
    """
    vertices, physical_edges = load_design_inputs(paths)
    off_net_sites = load_off_net_sites(paths.off_net_path) if paths.off_net_path else []
    vertices, physical_edges = dual_home(vertices, physical_edges, params, off_net_sites)
    vertices, physical_edges, overrides = apply_role_overrides(
        vertices, physical_edges, params, forced_connections, excluded_connections
    )
    design = synthesize_three_tier_design(vertices, physical_edges, params, overrides)
    vertices, physical_edges, design, validation = finalize(
        vertices, physical_edges, design, params
    )
    return DesignArtifacts(vertices, physical_edges, design, validation)


def _ring_inputs() -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge]]:
    """The ring vertices and physical edges."""
    return ring_vertices(), ring_physical_edges()


def ring_artifacts() -> DesignArtifacts:
    """Run the synthesizer over the in-memory ring and bundle the artifacts."""
    vertices, edges = _ring_inputs()
    design = synthesize_three_tier_design(vertices, edges, ring_params())
    vertices, edges = materialize_selected_colocation_twins(vertices, edges, design)
    return DesignArtifacts(vertices, edges, design, validate_design(vertices, design))


RingInputs = tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge]]


def ring_inputs_with_roadm(roadm_id: str) -> RingInputs:
    """Ring inputs with one PoP recast as a transit-only ROADM."""
    vertices, edges = _ring_inputs()
    vertices = [
        dataclasses.replace(vertex, kind=KIND_ROADM) if vertex.id == roadm_id else vertex
        for vertex in vertices
    ]
    return vertices, edges


def _forced_artifacts(
    params: DesignParams,
    inputs: RingInputs | None = None,
    forced_connections: tuple[ForcedConnection, ...] = (),
) -> DesignArtifacts:
    """Run the ring synthesizer with operator pins resolved through the CLI's path.

    Resolving via ``apply_role_overrides`` -- the same step ``run_design`` takes --
    means the artifacts reflect genuinely honored force-core/force-aggregation
    requests rather than emergent selections.
    """
    vertices, edges = inputs if inputs is not None else _ring_inputs()
    vertices, edges, overrides = apply_role_overrides(vertices, edges, params, forced_connections)
    design = synthesize_three_tier_design(vertices, edges, params, overrides)
    vertices, edges = materialize_selected_colocation_twins(vertices, edges, design)
    return DesignArtifacts(vertices, edges, design, validate_design(vertices, design))


def forced_aggregation_artifacts(name: str) -> DesignArtifacts:
    """Ring artifacts with one PoP forced onto the aggregation tier."""
    return _forced_artifacts(DesignParams(min_core_count=2, forced_aggregation_names=(name,)))


def forced_roadm_aggregation_artifacts(name: str) -> DesignArtifacts:
    """Ring artifacts forcing a transit-only ROADM onto the aggregation tier.

    ROADMs are eligible like any other point now, and a force always wins regardless
    -- the mechanism the Joint Great Falls/Minot pins use.
    """
    params = DesignParams(min_core_count=2, forced_aggregation_names=(name,))
    return _forced_artifacts(params, ring_inputs_with_roadm(name))


def forced_core_artifacts(name: str) -> DesignArtifacts:
    """Ring artifacts with one PoP forced onto the core tier."""
    return _forced_artifacts(DesignParams(min_core_count=2, forced_core_names=(name,)))


def prohibited_aggregation_artifacts(name: str) -> DesignArtifacts:
    """Ring artifacts forcing a PoP as a core while barring it from the aggregation tier.

    Pairing the force-core pin with the prohibition exercises the distinctive
    behavior: the PoP must land on the core tier yet never reach the aggregation
    tier, not even through its co-located twin.
    """
    return _forced_artifacts(
        DesignParams(
            min_core_count=2,
            forced_core_names=(name,),
            exclusions=RoleExclusions(prohibited_aggregation_names=(name,)),
        )
    )


def forced_connection_artifacts(
    params: DesignParams, forced_connections: tuple[ForcedConnection, ...]
) -> DesignArtifacts:
    """Ring artifacts for operator pins plus forced connections, resolved via overrides."""
    return _forced_artifacts(params, forced_connections=forced_connections)


def write_solvable_design_paths(directory: Path) -> DesignPaths:
    """Write the solvable ring of Lumen PoPs and F-35 installations as a DesignPaths.

    Same vertices as :func:`write_solvable_inputs`, but bundled as a
    :class:`DesignPaths` ready to hand straight to :func:`run_design`.
    """
    pops = [
        (name, lat, lon, "PoP", "Not shown in map", "")
        for name, (lat, lon) in {**RING_COORDS, **SPUR_COORDS}.items()
    ]
    lumen_path = directory / "lumen.csv"
    _write_csv(lumen_path, VERTEX_HEADER, pops)
    access = [
        (name, lat, lon, "Military installation", "Shown in map", "")
        for name, (lat, lon) in ACCESS_COORDS.items()
    ]
    f35_path = directory / "f35.csv"
    _write_csv(f35_path, VERTEX_HEADER, access)
    edges_path = directory / "ring_edges.csv"
    edges_path.write_text(solvable_edges_csv(), encoding="utf-8")
    return DesignPaths((("F-35", f35_path), ("Lumen", lumen_path)), edges_path)


def write_off_net_solvable_inputs(directory: Path) -> tuple[DesignPaths, str]:
    """Write the solvable ring plus an off-net site CSV near two ring PoPs.

    Returns the :class:`DesignPaths` (with ``off_net_path`` set) and the off-net
    site's name, ready to force as a core or aggregation through :func:`run_design`.
    """
    vertex_files = write_vertex_files(directory, solvable_tenant_rows())
    edges_path = directory / "ring_edges.csv"
    edges_path.write_text(solvable_edges_csv(), encoding="utf-8")
    off_net_path = directory / "off_net.csv"
    off_net_path.write_text(
        "name,latitude,longitude\nDulles Hub,40.5,-100.0\n", encoding="utf-8"
    )
    return DesignPaths(vertex_files, edges_path, off_net_path=off_net_path), "Dulles Hub"


def sample_sources() -> SourceFiles:
    """Provenance paths for output rendering tests."""
    return SourceFiles((Path("vertices/lumen.csv"),), Path("edges.csv"))
