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

from synthesizer.codec import OFF_NET_KIND, PROVIDER_KIND, SITE_KIND
from synthesizer.input_graph import PhysicalEdge, Vertex, VertexInfo, edge_key
from synthesizer.model import (
    KIND_ROADM,
    Design,
    DesignArtifacts,
    DesignMetrics,
    DesignParams,
    ForcedConnection,
    PathUse,
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
# PoP has a distinct ``(municipality, state)`` the data-center gate can key on. The
# country makes the tooltip's display rule resolve to the state, as for any US place.
_FIXTURE_STATE = "XX"
_FIXTURE_COUNTRY = "United States"


def carrier_pop(vertex_id: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build a carrier PoP vertex (a backbone PoP)."""
    return Vertex(
        id=vertex_id,
        name=vertex_id,
        kind="PoP",
        coords=(lat, lon),
        info=VertexInfo(
            municipality=vertex_id, state=_FIXTURE_STATE, country=_FIXTURE_COUNTRY
        ),
    )


def access_vertex(vertex_id: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build a tenant-site demand vertex."""
    return Vertex(id=vertex_id, name=vertex_id, kind=SITE_KIND, coords=(lat, lon))


def provider_vertex(vertex_id: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build a provider-region demand vertex."""
    return Vertex(id=vertex_id, name=vertex_id, kind=PROVIDER_KIND, coords=(lat, lon))


def off_net_site(vertex_id: str, lat: float = 0.0, lon: float = 0.0) -> Vertex:
    """Build an off-net candidate site: not a carrier PoP and carrying no demand."""
    return Vertex(
        id=vertex_id,
        name=vertex_id,
        kind=OFF_NET_KIND,
        coords=(lat, lon),
        info=VertexInfo(
            municipality=vertex_id, state=_FIXTURE_STATE, country=_FIXTURE_COUNTRY
        ),
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


# A three-node backbone mesh in two routings, the pair the independence check exists to
# tell apart: in the first, node a's links to b and to c both cross transit city x, so one
# city's loss takes both and a holds a single independent link; in the second, a's second
# link is rerouted through x's alternative y and both links stand on their own. Node b and
# node c hold two independent links in either routing.
SHARED_TRANSIT_BACKBONE = ("a", "b", "c")
SHARED_TRANSIT_ROUTES = [("a", "x", "b"), ("a", "x", "c"), ("b", "c")]
DIVERSE_TRANSIT_ROUTES = [("a", "x", "b"), ("a", "y", "c"), ("b", "c")]


def meshed_backbone_design(
    routes: list[tuple[str, ...]], backbone_ids: tuple[str, ...]
) -> Design:
    """A design whose backbone mesh rides the given routed paths, one link per route.

    Shared by the tiers that judge a routed mesh rather than build one: each route's ends
    are its link's endpoints, so the cities in between are the link's transit.
    """
    return Design(
        backbone_ids=backbone_ids,
        transit_ids=(),
        access_edges=[],
        physical_edge_keys=set(),
        path_uses=[
            PathUse("backbone_mesh", route[0], route[-1], route, 1.0) for route in routes
        ],
        metrics=DesignMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
    )


def carrier_pops_by_id(vertex_ids: str) -> dict[str, Vertex]:
    """A carrier PoP per single-character id, keyed by id, for validation lookups."""
    return {vertex_id: carrier_pop(vertex_id) for vertex_id in vertex_ids}


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
    the AFGSC Great Falls/Minot pins use.
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


# A four-PoP square around one central PoP. Short spokes to the centre and longer ring
# edges make every diagonal backbone-mesh link route through the centre, so once the four
# corners are the backbone the centre carries four of the design's lines as a transit
# node. The convergence pass (issue #4) then promotes the centre when it is a data-center
# city. Coordinates are a degenerate diamond; distances are pinned in
# :func:`convergence_hub_inputs` so the diagonals are strictly shorter through the centre.
_HUB_CORNERS = ("hub_b0", "hub_b1", "hub_b2", "hub_b3")
_HUB_CENTER = "hub_dc"
_HUB_COORDS = {
    "hub_b0": (1.0, 0.0),
    "hub_b1": (0.0, 1.0),
    "hub_b2": (-1.0, 0.0),
    "hub_b3": (0.0, -1.0),
    "hub_dc": (0.0, 0.0),
}


def convergence_hub_inputs() -> RingInputs:
    """The square-plus-centre carrier graph the convergence fixture is built on."""
    pops = [carrier_pop(n, *_HUB_COORDS[n]) for n in (*_HUB_CORNERS, _HUB_CENTER)]
    spokes = {(_HUB_CENTER, corner): 1.0 for corner in _HUB_CORNERS}
    ring = {
        (_HUB_CORNERS[i], _HUB_CORNERS[(i + 1) % 4]): 1.5 for i in range(4)
    }
    return pops, physical_edges_from({**spokes, **ring})


def convergence_hub_artifacts(
    promote_hub: bool = True,
    max_backbone_count: int | None = None,
    promote_convergences: bool = True,
) -> DesignArtifacts:
    """Run the synthesizer with the four corners forced and the centre left transit.

    The diagonal backbone-mesh links route through the centre, so it carries four of the
    design's lines. When ``promote_hub`` is set the centre is a data-center city and the
    convergence pass promotes it into the backbone and redraws; otherwise the centre is
    barred from the gate and stays transit. A ``max_backbone_count`` of four (the four
    forced corners) leaves no room for the promotion, so the centre stays transit even
    though it qualifies -- the cap wins. ``promote_convergences=False`` disables the
    promotion pass entirely, so the centre stays transit even at a data-center city.
    """
    vertices, edges = convergence_hub_inputs()
    datacenter_cities = frozenset(
        (corner, _FIXTURE_STATE) for corner in _HUB_CORNERS
    )
    if promote_hub:
        datacenter_cities = datacenter_cities | {(_HUB_CENTER, _FIXTURE_STATE)}
    params = DesignParams(
        min_backbone_count=2,
        max_backbone_count=max_backbone_count,
        forced_backbone_names=_HUB_CORNERS,
        datacenter_cities=datacenter_cities,
        promote_high_degree_convergences=promote_convergences,
    )
    vertices, edges, overrides = apply_role_overrides(vertices, edges, params, (), ())
    design = synthesize_two_tier_design(vertices, edges, params, overrides)
    return DesignArtifacts(vertices, edges, design, validate_design(vertices, design))


def sample_sources() -> SourceFiles:
    """Provenance paths for output rendering tests."""
    return SourceFiles((Path("vertices/lumen.csv"),), Path("edges.csv"))
