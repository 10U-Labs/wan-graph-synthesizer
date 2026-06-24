"""Shared test fixtures: vertex factories and an in-memory ring graph.

Centralized so unit, integration, and e2e tests reuse identical inputs without
duplicating data (which copy-paste detection would otherwise flag). Designs are driven
from in-memory ``Vertex``/``PhysicalEdge`` objects -- production reads the stored simple
rows via :mod:`synthesizer.codec`; only the suite builds a design straight from objects.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from synthesizer.codec import OFF_NET_KIND
from synthesizer.input_graph import PhysicalEdge, Vertex, edge_key
from synthesizer.model import (
    KIND_ROADM,
    DesignArtifacts,
    DesignParams,
    ForcedConnection,
    RoleExclusions,
    SourceFiles,
)
from synthesizer.synthesize import synthesize_three_tier_design
from synthesizer.overrides import apply_role_overrides, materialize_selected_colocation_twins
from synthesizer.stages import dual_home, finalize
from synthesizer.validation import validate_design

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
    """Build a carrier PoP vertex (a backbone PoP, not shown on the map)."""
    return Vertex(id=vertex_id, name=vertex_id, kind="PoP", coords=(lat, lon), shown_in_map=False)


def access_vertex(vertex_id: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build an access (installation) vertex."""
    return Vertex(id=vertex_id, name=vertex_id, kind="Military installation", coords=(lat, lon))


def off_net_site(vertex_id: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build an off-net candidate site: not a carrier PoP and carrying no demand."""
    return Vertex(id=vertex_id, name=vertex_id, kind=OFF_NET_KIND, coords=(lat, lon))


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


RingInputs = tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge]]


def _ring_inputs() -> RingInputs:
    """The ring vertices and physical edges."""
    return ring_vertices(), ring_physical_edges()


def run_design(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    params: DesignParams,
    off_net_sites: list[Vertex] | None = None,
) -> DesignArtifacts:
    """Drive the whole pipeline from in-memory inputs -- the suite's design driver.

    Mirrors the steps the Fargate entrypoint runs inline (dual-home -> overrides ->
    synthesize -> finalize); kept in test support because no shipped code drives a
    design from raw objects. Operator pins arrive through ``params``; the standalone
    forced-connection path is exercised separately via :func:`forced_connection_artifacts`.
    """
    vertices, physical_edges = dual_home(vertices, physical_edges, params, off_net_sites or [])
    vertices, physical_edges, overrides = apply_role_overrides(
        vertices, physical_edges, params, (), ()
    )
    design = synthesize_three_tier_design(vertices, physical_edges, params, overrides)
    vertices, physical_edges, design, validation = finalize(
        vertices, physical_edges, design, params
    )
    return DesignArtifacts(vertices, physical_edges, design, validation)


def ring_artifacts() -> DesignArtifacts:
    """Run the synthesizer over the in-memory ring and bundle the artifacts."""
    vertices, edges = _ring_inputs()
    design = synthesize_three_tier_design(vertices, edges, ring_params())
    vertices, edges = materialize_selected_colocation_twins(vertices, edges, design)
    return DesignArtifacts(vertices, edges, design, validate_design(vertices, design))


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


def sample_sources() -> SourceFiles:
    """Provenance paths for output rendering tests."""
    return SourceFiles((Path("vertices/lumen.csv"),), Path("edges.csv"))
