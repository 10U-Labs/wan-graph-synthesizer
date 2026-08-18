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
    DesignInputs,
    DesignMetrics,
    DesignParams,
    ForcedLinks,
    OperatorLinks,
    DesignPath,
    RoleExclusions,
    SourceFiles,
    Tuning,
)
from synthesizer.graphs import biconnected_block_membership, build_adjacency
from synthesizer.search_plan import _SearchPlan
from synthesizer.synthesize import all_pairs_shortest, synthesize_two_tier_design
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
# link is redrawn through x's alternative y and both links stand on their own. Node b and
# node c hold two independent links in either routing.
SHARED_TRANSIT_BACKBONE = ("a", "b", "c")
SHARED_TRANSIT_PATHS = [("a", "x", "b"), ("a", "x", "c"), ("b", "c")]
DIVERSE_TRANSIT_PATHS = [("a", "x", "b"), ("a", "y", "c"), ("b", "c")]


def meshed_backbone_design(
    paths: list[tuple[str, ...]], backbone_ids: tuple[str, ...]
) -> Design:
    """A design whose backbone mesh rides the given paths, one link per path.

    Shared by the tiers that judge a drawn mesh rather than build one: each path's ends
    are its link's endpoints, so the cities in between are the link's transit.
    """
    return Design(
        backbone_ids=backbone_ids,
        transit_ids=(),
        access_edges=[],
        physical_edge_keys=set(),
        path_uses=[
            DesignPath("backbone_mesh", path[0], path[-1], path, 1.0) for path in paths
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
    design from raw objects. Operator pins arrive through ``params``; the written-link
    path is exercised separately via :func:`forced_link_artifacts`.
    """
    vertices, physical_edges = dual_home(vertices, physical_edges, params, off_net_sites or [])
    vertices, physical_edges, overrides = apply_role_overrides(vertices, physical_edges, params)
    design = synthesize_two_tier_design(vertices, physical_edges, params, overrides)
    vertices, physical_edges, design, validation = finalize(
        vertices, physical_edges, design, params, overrides.degree_exempt_backbone_ids
    )
    return DesignArtifacts(vertices, physical_edges, design, validation)


def mesh_paths(artifacts: DesignArtifacts) -> list[DesignPath]:
    """The backbone paths of a finished design, without the access paths homing into it.

    A design carries both, and almost every assertion about a backbone is about the first
    kind alone. Read here rather than in each test file because four of them ask for it in
    the same words.
    """
    return [use for use in artifacts.design.path_uses if use.purpose == "backbone_mesh"]


def design_over_segments(
    site_ids: tuple[str, ...],
    segments: dict[tuple[str, str], float],
    number_of_diverse_paths: int,
    transit_ids: tuple[str, ...] = (),
    min_backbone_count: int | None = None,
) -> DesignArtifacts:
    """Run the whole pipeline over a segment map written by hand, every site in the backbone.

    Several integration tests in this suite work the same way: name a few sites, price the
    fiber between them, force every one of them into the backbone and ask for a number of
    diverse paths. Written down once because only the map and the number change between
    them, and three copies of the same parameters is what the copy-paste gate is for.

    ``transit_ids`` are cities the fiber crosses that no provider has a cage in, so they can
    carry a path without taking a backbone seat. ``min_backbone_count`` is how few sites the
    search may settle for and defaults to all of them.
    """
    cities = site_ids + transit_ids
    fewest = len(site_ids) if min_backbone_count is None else min_backbone_count
    return run_design(
        [
            carrier_pop(city, 38.0, -115.0 + 2.0 * index)
            for index, city in enumerate(cities)
        ],
        physical_edges_from(segments),
        DesignParams(
            min_backbone_count=fewest,
            max_backbone_count=len(site_ids),
            forced_backbone_names=site_ids,
            datacenter_cities=frozenset((site, "XX") for site in site_ids),
            promote_high_degree_convergences=False,
            tuning=Tuning(backbone_number_of_diverse_paths=number_of_diverse_paths),
        ),
    )


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
    links: OperatorLinks = OperatorLinks(),
) -> DesignArtifacts:
    """Run the ring synthesizer with operator pins resolved through the CLI's path.

    Resolving via ``apply_role_overrides`` -- the same step ``run_design`` takes --
    means the artifacts reflect genuinely honored force-backbone requests rather than
    emergent selections. Validation goes through ``finalize`` for the same reason: the
    report then answers to the degrees ``params`` configures, not to the defaults.
    """
    vertices, edges = inputs if inputs is not None else _ring_inputs()
    vertices, edges, overrides = apply_role_overrides(vertices, edges, params, links)
    design = synthesize_two_tier_design(vertices, edges, params, overrides)
    vertices, edges, design, validation = finalize(
        vertices, edges, design, params, overrides.degree_exempt_backbone_ids
    )
    return DesignArtifacts(vertices, edges, design, validation)


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


def ring_inputs_with_demand(access_id: str, at_pop: str) -> RingInputs:
    """Ring inputs plus one demand vertex sitting on a named ring PoP's coordinates.

    The ring carries carrier PoPs only, so a case about where demand homes has to supply
    its own. Placing the site on top of ``at_pop`` makes that PoP its nearest node by
    construction, which is what lets a forced home elsewhere be told apart from the
    distance-ranked choice.
    """
    vertices, edges = _ring_inputs()
    return [*vertices, access_vertex(access_id, *RING_COORDS[at_pop])], edges


def forced_link_artifacts(
    params: DesignParams, links: OperatorLinks, inputs: RingInputs | None = None
) -> DesignArtifacts:
    """Ring artifacts for operator pins plus written links, resolved via overrides."""
    return _forced_artifacts(params, inputs, links)


# A four-PoP square around one central PoP. Short spokes to the centre and longer ring
# edges make every diagonal backbone-mesh link run through the centre, so once the four
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

    The diagonal backbone-mesh links run through the centre, so it carries four of the
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
    vertices, edges, overrides = apply_role_overrides(vertices, edges, params)
    design = synthesize_two_tier_design(vertices, edges, params, overrides)
    return DesignArtifacts(vertices, edges, design, validate_design(vertices, design))


def sample_sources() -> SourceFiles:
    """Provenance paths for output rendering tests."""
    return SourceFiles((Path("vertices/lumen.csv"),), Path("edges.csv"))


def design_inputs_from_edges(
    edge_ids: list[str],
    edges: dict[tuple[str, str], PhysicalEdge],
    eligible: set[str],
    access_vertices: list[Vertex] | None = None,
    coords: dict[str, tuple[float, float]] | None = None,
) -> DesignInputs:
    """Build DesignInputs over a mileage-weighted graph for direct synthesizer tests.

    ``edge_ids`` are the carrier PoPs (the backbone candidates). ``edges`` may also
    wire the demand vertices into the physical graph -- in the two-tier model demand
    homes to the backbone over the physical graph, so any demand that must home is
    given edges here while staying out of ``edge_ids`` (it is not a carrier PoP).
    """
    places = coords or {}
    pops = [carrier_pop(vertex_id, *places.get(vertex_id, (0.0, 0.0))) for vertex_id in edge_ids]
    adjacency = build_adjacency(edges)
    distances, predecessors = all_pairs_shortest(pops, adjacency)
    return DesignInputs(
        access_vertices=access_vertices if access_vertices is not None else [],
        carrier_pops=pops,
        physical_edges=edges,
        eligible_backbone_ids=eligible,
        adjacency=adjacency,
        all_distances=distances,
        all_predecessors=predecessors,
        carrier_blocks=biconnected_block_membership(adjacency),
    )


def search_plan(
    candidates: list[str],
    strength: dict[str, float] | None = None,
    access_backbone_links: int = 2,
    forced_links: ForcedLinks | None = None,
) -> _SearchPlan:
    """Build a search plan for direct synthesizer tests.

    When no strength map is given, every candidate gets equal strength, so the search
    falls back to its last-mile tie-break.
    """
    strength_by_id = strength if strength is not None else {name: 1.0 for name in candidates}
    return _SearchPlan(
        candidates,
        strength_by_id,
        tuning=Tuning(access_backbone_links=access_backbone_links),
        forced_links=forced_links or ForcedLinks(),
    )


TRIANGLE = physical_edges_from({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0})


# --- segment count against path diversity: the one graph where the two measures disagree ----
#
# Every other fixture here is a ring, a small cluster or a clique, and on all three a site's
# segment count and its diverse path count are the same number: ring sites have two segments and
# two paths, clique sites turn every segment into a path. So none of them can tell a ranking by
# segments from a ranking by diversity, and this graph exists to.
#
# ``funnel`` and ``second_funnel`` have five segments each and ``spread`` has three. Four of
# each funnel's segments reach the same upstream city ``choke_east`` and the fifth reaches
# ``choke_west``, so however many segments a funnel has, every path out of it crosses one of
# those two cities and it can hold two paths that fail independently. The spread's three
# segments go to three separate cities, each of which is itself a candidate, so it can hold
# three. Segment count therefore ranks both funnels above the spread and path diversity ranks
# the spread above both.
#
# There are two funnels rather than one so that a two-seat backbone has to choose. With one,
# the spread places second under either measure and the chosen backbone is the same either
# way, which would let a synthesis pass while ranking by the wrong thing.
#
# The funnelled segments leave eastward together, because fiber that converges on one upstream
# city is fiber pointing one way -- so the compass term is not carrying this fixture's
# disagreement. Under the segment-count term a funnel scored a full 1.0 against the spread's
# 0.6; under the diversity term it scores 2/3 against the spread's 1.0.
FUNNEL_EDGES = physical_edges_from({
    ("funnel", "east_a"): 40.0,
    ("funnel", "east_b"): 45.0,
    ("funnel", "east_c"): 50.0,
    ("funnel", "east_d"): 55.0,
    ("funnel", "west_a"): 60.0,
    ("east_a", "choke_east"): 40.0,
    ("east_b", "choke_east"): 45.0,
    ("east_c", "choke_east"): 50.0,
    ("east_d", "choke_east"): 55.0,
    ("west_a", "choke_west"): 60.0,
    ("second_funnel", "east_e"): 40.0,
    ("second_funnel", "east_f"): 45.0,
    ("second_funnel", "east_g"): 50.0,
    ("second_funnel", "east_h"): 55.0,
    ("second_funnel", "west_b"): 60.0,
    ("east_e", "choke_east"): 40.0,
    ("east_f", "choke_east"): 45.0,
    ("east_g", "choke_east"): 50.0,
    ("east_h", "choke_east"): 55.0,
    ("west_b", "choke_west"): 60.0,
    ("choke_east", "north"): 70.0,
    ("choke_east", "south"): 70.0,
    ("choke_west", "west"): 70.0,
    ("spread", "north"): 80.0,
    ("spread", "south"): 80.0,
    ("spread", "west"): 80.0,
})
FUNNEL_IDS = [
    "funnel", "second_funnel", "spread", "north", "south", "west",
    "east_a", "east_b", "east_c", "east_d", "west_a",
    "east_e", "east_f", "east_g", "east_h", "west_b",
    "choke_east", "choke_west",
]
# Only the six sites the measures are compared over are gate-eligible; the spurs and the
# two single points of failure are transit the paths pass through, not places a backbone
# node may sit.
FUNNEL_ELIGIBLE = {"funnel", "second_funnel", "spread", "north", "south", "west"}
FUNNEL_COORDS = {
    "funnel": (40.0, -100.0),
    "east_a": (40.0, -99.0), "east_b": (40.05, -99.0),
    "east_c": (39.95, -99.0), "east_d": (40.0, -98.9),
    "west_a": (40.0, -101.0),
    "second_funnel": (36.0, -100.0),
    "east_e": (36.0, -99.0), "east_f": (36.05, -99.0),
    "east_g": (35.95, -99.0), "east_h": (36.0, -98.9),
    "west_b": (36.0, -101.0),
    "choke_east": (38.0, -98.0), "choke_west": (38.0, -102.0),
    "north": (42.0, -108.0), "south": (34.0, -108.0), "west": (38.0, -110.0),
    "spread": (38.0, -108.0),
}


def funnel_vertices() -> list[Vertex]:
    """The disagreement graph's sites, each a carrier PoP at its fixture coordinates."""
    return [carrier_pop(vertex_id, *FUNNEL_COORDS[vertex_id]) for vertex_id in FUNNEL_IDS]


def funnel_datacenter_cities() -> frozenset[tuple[str, str]]:
    """Only the six compared sites pass the gate; the rest stay transit."""
    return frozenset((vertex_id, _FIXTURE_STATE) for vertex_id in FUNNEL_ELIGIBLE)


# Three backbone sites within twenty miles of each other, all reaching one another over
# ``pdx``, and all reaching one another again over ``tok`` a thousand miles offshore. The
# overland paths share ``pdx``, so a proof counting only disjoint paths takes the
# crossing as a second way out and the mesh is wired along it -- two thousand miles of
# fiber standing in for twenty. It is the one fixture whose segments differ by orders of
# magnitude, which is what the backup path multiple is measured against.
CROSSING_EDGES = physical_edges_from({
    ("sea", "pdx"): 10.0,
    ("pdx", "hil"): 10.0,
    ("pdx", "eug"): 10.0,
    ("sea", "tok"): 1000.0,
    ("tok", "hil"): 1000.0,
    ("tok", "eug"): 1000.0,
})
CROSSING_IDS = ["sea", "hil", "eug", "pdx", "tok"]
# The three compared sites are seatable; ``pdx`` and ``tok`` are transit the paths pass
# through, never places a backbone node may sit -- which is what keeps ``tok`` a crossing
# rather than a peer a path may legitimately end at.
CROSSING_ELIGIBLE = {"sea", "hil", "eug"}
CROSSING_COORDS = {
    "sea": (47.6, -122.3),
    "pdx": (45.5, -122.7),
    "hil": (45.5, -123.0),
    "eug": (44.0, -123.1),
    "tok": (35.7, 139.7),
}


def crossing_vertices() -> list[Vertex]:
    """The crossing graph's sites, each a carrier PoP at its fixture coordinates."""
    return [carrier_pop(vertex_id, *CROSSING_COORDS[vertex_id]) for vertex_id in CROSSING_IDS]


def crossing_datacenter_cities() -> frozenset[tuple[str, str]]:
    """Only the three compared sites pass the gate, so pdx and tok stay transit."""
    return frozenset((vertex_id, _FIXTURE_STATE) for vertex_id in CROSSING_ELIGIBLE)


# Three backbone sites reaching one another over three shared hub cities, priced so the
# shortest way out of one site is not the shortest way back out of another. That is what
# makes the two ends of a pair prove different fiber to each other: each proof is the
# shortest set of paths out of its own site, and the two sites have different other peers
# to keep clear of. ``a`` is short through ``h2`` and long through ``h1``, ``b`` is the
# other way round, and ``c`` is cheap through both -- so a proves h1 to b and h2 to c, b
# proves h1 to a and h3 to c, and c proves h2 to a and h1 to b. Only the pair b-c is proved
# twice: five miles the way b proved it and two the way c did.
SHARED_HUB_SEGMENTS = {
    ("a", "h1"): 400.0, ("a", "h2"): 100.0, ("a", "h3"): 800.0,
    ("b", "h1"): 100.0, ("b", "h2"): 800.0, ("b", "h3"): 200.0,
    ("c", "h1"): 100.0, ("c", "h2"): 200.0, ("c", "h3"): 300.0,
}
# The same three sites with a fourth, ``d``, joined to ``b`` and to ``c`` over fiber of its
# own. It is what leaves ``b`` a way out that no hub carries: b's paths to a and to c both
# ride ``h1``, and the path to d is its second independently failing link. Without d the
# only way out b has left that a single city's loss would not take with its first is a
# second path to c, which is fiber for a pair that is joined already.
SHARED_HUB_PEER_EDGES = physical_edges_from({
    **SHARED_HUB_SEGMENTS,
    ("b", "d1"): 100.0, ("d1", "d"): 300.0,
    ("c", "d2"): 100.0, ("d2", "d"): 300.0,
})
SHARED_HUB_PEER_SITES = ("a", "b", "c", "d")
SHARED_HUB_PEER_IDS = ("a", "b", "c", "d", "h1", "h2", "h3", "d1", "d2")


def shared_hub_peer_vertices() -> list[Vertex]:
    """The four-site graph's cities, spread along a line so no two share coordinates."""
    return [
        carrier_pop(vertex_id, 38.0, -115.0 + 2.0 * index)
        for index, vertex_id in enumerate(SHARED_HUB_PEER_IDS)
    ]


def shared_hub_peer_datacenter_cities() -> frozenset[tuple[str, str]]:
    """Only the four sites pass the gate, so no hub or corridor city takes a seat."""
    return frozenset((vertex_id, _FIXTURE_STATE) for vertex_id in SHARED_HUB_PEER_SITES)


def shared_hub_peer_artifacts(asked_for: int = 2) -> DesignArtifacts:
    """The design the whole pipeline settles on over the four-site graph.

    Every site is seated and the seats are capped at the four, so the tenant's config says
    each site has peers to reach and every pair of them is allowed one path.
    """
    return run_design(
        shared_hub_peer_vertices(),
        SHARED_HUB_PEER_EDGES,
        DesignParams(
            min_backbone_count=len(SHARED_HUB_PEER_SITES),
            max_backbone_count=len(SHARED_HUB_PEER_SITES),
            forced_backbone_names=SHARED_HUB_PEER_SITES,
            datacenter_cities=shared_hub_peer_datacenter_cities(),
            promote_high_degree_convergences=False,
            tuning=Tuning(backbone_number_of_diverse_paths=asked_for),
        ),
    )


# The crossing graph with one of its peers moved seven thousand miles away, which is what
# lets a bound applied segment by segment be met and a bound applied to the finished path be
# broken (GitHub issue #45). ``sea`` is twenty miles from ``hil`` over ``pdx`` and seven
# thousand from ``syd``, so syd's allowance is large enough to keep both ``tok`` segments and
# hil's is nowhere near. Only ``pdx`` reaches ``syd``, so sea's two paths cannot both take
# it and the second is left the crossing -- landing on ``hil``, at a hundred times what hil
# allows. ``hil``--``syd`` closes the ring, so no single city's loss splits the fiber and
# the search will seat all three.
DISTANT_PEER_EDGES = physical_edges_from({
    ("sea", "pdx"): 10.0,
    ("pdx", "hil"): 10.0,
    ("sea", "tok"): 1000.0,
    ("tok", "hil"): 1000.0,
    ("pdx", "syd"): 7000.0,
    ("hil", "syd"): 7000.0,
})
DISTANT_PEER_IDS = ["sea", "hil", "syd", "pdx", "tok"]
# The three peers are seatable; ``pdx`` and ``tok`` are transit, on the same terms as the
# crossing graph above.
DISTANT_PEER_ELIGIBLE = {"sea", "hil", "syd"}
DISTANT_PEER_COORDS = {
    "sea": (47.6, -122.3),
    "pdx": (45.5, -122.7),
    "hil": (45.5, -123.0),
    "syd": (-33.9, 151.2),
    "tok": (35.7, 139.7),
}


def distant_peer_vertices() -> list[Vertex]:
    """The distant-peer graph's sites, each a carrier PoP at its fixture coordinates."""
    return [
        carrier_pop(vertex_id, *DISTANT_PEER_COORDS[vertex_id])
        for vertex_id in DISTANT_PEER_IDS
    ]


def distant_peer_datacenter_cities() -> frozenset[tuple[str, str]]:
    """Only the three peers pass the gate, so pdx and tok stay transit."""
    return frozenset((vertex_id, _FIXTURE_STATE) for vertex_id in DISTANT_PEER_ELIGIBLE)


# Three sites on a ring of one-mile segments, each also joined to the other two by an express
# segment of five. Every pair is two miles apart round the ring through one transit city and
# five miles apart down the express segment, so the express segments cross fewer cities and run
# two and a half times the fiber miles. Both ways of wiring the ring are the same two independent
# links per site, and both sit inside a backup path multiple of three, so nothing but the
# mileage tells them apart: the ring comes to six miles of mesh and the express segments to
# fifteen (GitHub issue #57).
EXPRESS_EDGES = physical_edges_from({
    ("sea", "pdx"): 1.0,
    ("pdx", "hil"): 1.0,
    ("hil", "alb"): 1.0,
    ("alb", "eug"): 1.0,
    ("eug", "tac"): 1.0,
    ("tac", "sea"): 1.0,
    ("sea", "hil"): 5.0,
    ("hil", "eug"): 5.0,
    ("eug", "sea"): 5.0,
})
EXPRESS_IDS = ["sea", "hil", "eug", "pdx", "alb", "tac"]
# The three compared sites are seatable; ``pdx``, ``alb`` and ``tac`` are the transit the
# ring paths through, never places a backbone node may sit.
EXPRESS_ELIGIBLE = {"sea", "hil", "eug"}
EXPRESS_COORDS = {
    "sea": (47.6, -122.3),
    "pdx": (45.5, -122.7),
    "hil": (45.5, -123.0),
    "alb": (44.6, -123.1),
    "eug": (44.0, -123.1),
    "tac": (46.0, -122.9),
}


def express_vertices() -> list[Vertex]:
    """The ring graph's sites, each a carrier PoP at its fixture coordinates."""
    return [carrier_pop(vertex_id, *EXPRESS_COORDS[vertex_id]) for vertex_id in EXPRESS_IDS]


def express_datacenter_cities() -> frozenset[tuple[str, str]]:
    """Only the three compared sites pass the gate, so the ring's transit stays transit."""
    return frozenset((vertex_id, _FIXTURE_STATE) for vertex_id in EXPRESS_ELIGIBLE)


def funnel_inputs() -> DesignInputs:
    """The disagreement graph as design inputs, for scoring one site at a time."""
    return design_inputs_from_edges(
        FUNNEL_IDS, FUNNEL_EDGES, set(FUNNEL_ELIGIBLE), coords=FUNNEL_COORDS
    )


# --- physical biconnectivity: the search-time city-survivability gate --------------------

# Two triangles -- {a,b,c} and {d,e,f} -- joined only by the single segment c-d, so the two
# pockets share no biconnected block: no backbone may straddle them.
TWO_POCKET_EDGES = physical_edges_from(
    {
        ("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 1.0, ("c", "d"): 1.0,
        ("d", "e"): 1.0, ("e", "f"): 1.0, ("d", "f"): 1.0,
    }
)
TWO_POCKET_IDS = ["a", "b", "c", "d", "e", "f"]


# --- the fiber choice's separation search: a map that takes hundreds of passes -----------

# Twelve cities of carrier fiber, five of them backbone seats, priced in whole miles. The
# fiber choice writes its requirements down as an answer violates them, and on this map that
# takes 26 passes before the answer meets every requirement there is. That is what the
# fixture is for: a cap of 24 passes stood in ``synthesizer.survivable`` until GitHub issue
# #63, and every graph the suite had before this one is answered by the first solve or the
# one after it, so no test could reach a search that runs long enough for a cap to bind.
#
# Left to finish, the search buys seven segments running 159 miles, which is exactly the
# floor it publishes -- there is no shorter design meeting the same requirements. Stopped at
# 24 passes it buys thirteen segments running 291 against that same floor, and the design
# drawn over them orders 176 miles of fiber an operator pays for every month.
MANY_PASS_SEGMENTS = {
    ("a", "c"): 32.0, ("a", "e"): 22.0, ("a", "f"): 18.0, ("a", "g"): 25.0,
    ("b", "c"): 36.0, ("b", "h"): 30.0, ("b", "i"): 22.0,
    ("c", "e"): 22.0, ("c", "h"): 7.0, ("c", "i"): 25.0, ("c", "j"): 28.0,
    ("d", "f"): 36.0, ("d", "j"): 22.0, ("d", "k"): 7.0, ("d", "l"): 11.0,
    ("e", "f"): 39.0, ("e", "g"): 25.0, ("e", "h"): 21.0, ("e", "i"): 25.0,
    ("f", "j"): 25.0, ("f", "k"): 34.0,
    ("h", "i"): 18.0, ("h", "j"): 35.0,
    ("j", "k"): 16.0, ("j", "l"): 32.0,
    ("k", "l"): 18.0,
}
# The five seats, and the seven cities the fiber crosses that carry a path without taking a
# seat. Every seat has two ways out on this fiber, so none of them is lowered to what the
# carrier can carry and the finished design is one no site is short in.
MANY_PASS_SITES = ("c", "d", "j", "k", "l")
MANY_PASS_TRANSIT = ("a", "b", "e", "f", "g", "h", "i")
# What the search buys once it is allowed to finish, and the miles those segments run.
MANY_PASS_MILES = 159.0
