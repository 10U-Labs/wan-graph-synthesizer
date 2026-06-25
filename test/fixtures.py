"""Shared test fixtures: vertex factories and an in-memory ring graph.

Centralized so unit, integration, and e2e tests reuse identical inputs without
duplicating data (which copy-paste detection would otherwise flag). Designs are driven
from in-memory ``Vertex``/``PhysicalEdge`` objects -- production reads the stored simple
rows via :mod:`synthesizer.codec`; only the suite builds a design straight from objects.

The design is two tiers: a meshed ``backbone`` of selected carrier PoPs (each at a
data-center city) and the demand that homes into it. Carrier PoPs carry a ``(name, ST)``
city so the data-center gate can admit them; :func:`ring_datacenter_cities` covers every
PoP the ring fixtures build, keeping the ring feasible.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from synthesizer.codec import CSP_KIND, OFF_NET_KIND, SITE_KIND
from synthesizer.input_graph import PhysicalEdge, Vertex, VertexInfo, edge_key
from synthesizer.model import (
    KIND_ROADM,
    DesignArtifacts,
    DesignParams,
    ForcedConnection,
    RoleExclusions,
    SourceFiles,
)
from synthesizer.synthesize import synthesize_two_tier_design
from synthesizer.overrides import apply_role_overrides
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
RING_EDGE_PAIRS = [
    ("P0", "P1"),
    ("P1", "P2"),
    ("P2", "P3"),
    ("P3", "P4"),
    ("P4", "P5"),
    ("P5", "P0"),
    ("P0", "P6"),
]
# The state every fixture carrier PoP is placed in; the city is the PoP id, so each
# PoP has a distinct ``(municipality, state)`` the data-center gate can key on.
_FIXTURE_STATE = "XX"


def carrier_pop(vertex_id: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build a carrier PoP vertex (a backbone PoP, not shown on the map)."""
    return Vertex(
        id=vertex_id,
        name=vertex_id,
        kind="PoP",
        coords=(lat, lon),
        info=VertexInfo(municipality=vertex_id, state=_FIXTURE_STATE),
        shown_in_map=False,
    )


def access_vertex(vertex_id: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build a tenant-site demand vertex."""
    return Vertex(id=vertex_id, name=vertex_id, kind=SITE_KIND, coords=(lat, lon))


def csp_vertex(vertex_id: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build a CSP cloud-region demand vertex."""
    return Vertex(id=vertex_id, name=vertex_id, kind=CSP_KIND, coords=(lat, lon))


def off_net_site(vertex_id: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build an off-net candidate site: not a carrier PoP and carrying no demand."""
    return Vertex(
        id=vertex_id,
        name=vertex_id,
        kind=OFF_NET_KIND,
        coords=(lat, lon),
        info=VertexInfo(municipality=vertex_id, state=_FIXTURE_STATE),
    )


def ring_vertices() -> list[Vertex]:
    """Build the six-PoP ring plus a degree-one spur.

    The ring carries no non-PoP demand: in the two-tier model demand homes to the
    backbone over the *physical* graph, so a feasible end-to-end ring is its carrier
    PoPs alone. Demand-homing behaviour is exercised at the unit level, where the
    demand vertices are wired into the physical adjacency directly.
    """
    pops = [carrier_pop(n, lat, lon) for n, (lat, lon) in RING_COORDS.items()]
    pops += [carrier_pop(n, lat, lon) for n, (lat, lon) in SPUR_COORDS.items()]
    return pops


def ring_datacenter_cities() -> frozenset[tuple[str, str]]:
    """Every ring/spur PoP's ``(municipality, state)``, so all are gate-eligible."""
    return frozenset(
        (vertex_id, _FIXTURE_STATE) for vertex_id in (*RING_COORDS, *SPUR_COORDS)
    )


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
    """Design parameters that solve the ring with a two-node backbone."""
    return DesignParams(min_backbone_count=2, datacenter_cities=ring_datacenter_cities())


def forced_off_net_case() -> tuple[Vertex, DesignParams]:
    """An off-net site forced as backbone, plus params admitting its city to the gate."""
    site = off_net_site("Dulles Hub", 40.5, -100.0)
    params = DesignParams(
        min_backbone_count=2,
        forced_backbone_names=("Dulles Hub",),
        datacenter_cities=ring_datacenter_cities()
        | {(site.info.municipality, site.info.state)},
    )
    return site, params


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
    design = synthesize_two_tier_design(vertices, physical_edges, params, overrides)
    vertices, physical_edges, design, validation = finalize(
        vertices, physical_edges, design, params
    )
    return DesignArtifacts(vertices, physical_edges, design, validation)


def ring_artifacts() -> DesignArtifacts:
    """Run the synthesizer over the in-memory ring and bundle the artifacts."""
    vertices, edges = _ring_inputs()
    design = synthesize_two_tier_design(vertices, edges, ring_params())
    return DesignArtifacts(vertices, edges, design, validate_design(vertices, design))


def ring_inputs_with_roadm(roadm_id: str) -> RingInputs:
    """Ring inputs with one PoP recast as a transit-eligible ROADM."""
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
    means the artifacts reflect genuinely honored force-backbone requests rather than
    emergent selections.
    """
    vertices, edges = inputs if inputs is not None else _ring_inputs()
    vertices, edges, overrides = apply_role_overrides(
        vertices, edges, params, forced_connections, ()
    )
    design = synthesize_two_tier_design(vertices, edges, params, overrides)
    return DesignArtifacts(vertices, edges, design, validate_design(vertices, design))


def forced_backbone_artifacts(name: str) -> DesignArtifacts:
    """Ring artifacts with one PoP forced onto the backbone."""
    return _forced_artifacts(
        DesignParams(
            min_backbone_count=2,
            forced_backbone_names=(name,),
            datacenter_cities=ring_datacenter_cities(),
        )
    )


def forced_roadm_backbone_artifacts(name: str) -> DesignArtifacts:
    """Ring artifacts forcing a transit-eligible ROADM onto the backbone.

    ROADMs are eligible like any other point, and a force always wins -- the mechanism
    the Joint Great Falls/Minot pins use.
    """
    params = DesignParams(
        min_backbone_count=2,
        forced_backbone_names=(name,),
        datacenter_cities=ring_datacenter_cities(),
    )
    return _forced_artifacts(params, ring_inputs_with_roadm(name))


def prohibited_backbone_artifacts(name: str) -> DesignArtifacts:
    """Ring artifacts barring one PoP from the backbone."""
    return _forced_artifacts(
        DesignParams(
            min_backbone_count=2,
            exclusions=RoleExclusions(prohibited_backbone_names=(name,)),
            datacenter_cities=ring_datacenter_cities(),
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
