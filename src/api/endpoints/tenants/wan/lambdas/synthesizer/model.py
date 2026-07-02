"""The synthesizer's design vocabulary: tiers, tuning, routing, and validation.

These types build on the input-graph types in ``synthesizer.input_graph``
(``Vertex`` / ``PhysicalEdge`` and the geographic helpers); everything here is the
synthesizer's own in-memory representation, layered on top of them.

The design is two tiers: a meshed ``backbone`` of selected carrier PoPs (each at a
data-center city) and the demand that homes into it. Demand is labelled ``tenant``
(tenant sites) or ``csp`` (cloud regions); both home to the backbone identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from synthesizer.input_graph import PhysicalEdge, Vertex, VertexInfo


@dataclass(frozen=True)
class AccessEdge:
    """A logical link from a demand vertex (tenant site or CSP region) to a backbone PoP."""

    source: str
    target: str
    distance_miles: float

@dataclass(frozen=True)
class PathUse:
    """A routed path over the physical graph for one design purpose."""

    purpose: str
    source: str
    target: str
    path: tuple[str, ...]
    distance_miles: float

@dataclass
class DesignMetrics:
    """Mileage totals and the synthesis score for a design."""

    score: float
    access_miles: float
    physical_miles: float

@dataclass
class Design:
    """A complete two-tier design: the backbone, the demand it carries, routes, metrics."""

    backbone_ids: tuple[str, ...]
    transit_ids: tuple[str, ...]
    access_edges: list[AccessEdge]
    physical_edge_keys: set[tuple[str, str]]
    path_uses: list[PathUse]
    metrics: DesignMetrics

@dataclass(frozen=True)
class EnumBudget:
    """Memory budget governing how many backbone sets the search may enumerate."""

    memory_fraction: float = 0.6  # share of RAM the backbone enumeration may use
    set_peak_bytes: int = 160  # peak bytes one enumerated backbone set costs


@dataclass(frozen=True)
class Tuning:
    """Algorithm dials plus the two required redundancy degrees.

    The two degrees are operator requirements the design must meet, each its own
    REST resource (``backbone-mesh-degree`` / ``access-homing-degree``) with no
    default at the config layer; the values here are construction fallbacks only.
    ``backbone_mesh_degree`` is how many other backbone nodes each backbone node
    links to on the mesh; ``access_backbone_links`` is how many backbone nodes each
    demand vertex homes to. The remaining fields are the algorithm dials exposed
    together as the ``knobs`` resource.
    """

    compass_octants: int = 8  # compass sectors used to score a backbone node's link spread
    backbone_mesh_degree: int = 3  # other backbone nodes each one wires to (backbone-mesh-degree)
    backbone_coverage_target_miles: float = 600.0  # grow backbone until every demand is this near
    access_backbone_links: int = 2  # backbone nodes each demand vertex homes to
    enum_budget: EnumBudget = field(default_factory=EnumBudget)  # enumeration memory budget

# The two edge types a forced connection may pin, named as in ``README.md``.
FORCED_CONNECTION_TYPES = frozenset({"backbone-backbone", "access-backbone"})

@dataclass(frozen=True)
class ForcedConnection:
    """An operator-pinned edge between two named PoPs of a given edge type.

    ``edge_type`` is one of :data:`FORCED_CONNECTION_TYPES`; ``source`` and
    ``target`` are PoP display names (resolved to vertex ids by the overrides
    layer, like ``forced_backbone_names``). The endpoints must already be seated in
    the tiers the edge type requires (e.g. both backbone for ``backbone-backbone``).
    """

    edge_type: str
    source: str
    target: str

@dataclass(frozen=True)
class RoleExclusions:
    """Operator pins that bar a PoP from the backbone, by PoP display name.

    ``prohibited_backbone_names`` bar a PoP from the backbone tier. The overrides
    layer resolves them to vertex ids. (There is no demand bar: tenant/csp demand is
    inherent to the non-PoP vertices, not a tier the synthesizer assigns to a PoP.)
    """

    prohibited_backbone_names: tuple[str, ...] = ()

@dataclass(frozen=True)
class DesignParams:
    """Operator choices plus the algorithm :class:`Tuning` for the synthesis.

    ``datacenter_cities`` are the ``(municipality, state)`` pairs a colocation
    provider operates a facility in; a carrier PoP may serve as a backbone node only
    if its city is one of them. The set gates both the automatic backbone selection
    and the operator's forced pins.

    ``restrict_backbone_to_datacenters`` toggles that gate. When ``True`` (the default)
    the data-center-city gate is absolute, as above. When ``False`` -- the operator's
    free-for-all -- the gate is open: any carrier PoP with enough physical links is
    eligible, forced pins are accepted anywhere, and convergence hubs promote regardless
    of city. Candidates stay carrier PoPs either way; only the city filter changes.
    """

    min_backbone_count: int = 3  # minimum backbone nodes; the search adds more only if needed
    max_backbone_count: int | None = None  # ceiling on backbone nodes; None leaves it uncapped
    forced_backbone_names: tuple[str, ...] = ()  # PoPs pinned as backbone by the operator
    exclusions: RoleExclusions = field(default_factory=RoleExclusions)  # role bars
    datacenter_cities: frozenset[tuple[str, str]] = frozenset()  # cities a provider has a cage in
    restrict_backbone_to_datacenters: bool = True  # False => any carrier PoP may be backbone
    tuning: Tuning = field(default_factory=Tuning)

@dataclass(frozen=True)
class ForcedLinks:
    """Operator-forced edges (and backbone pins) resolved to vertex ids.

    ``backbone`` holds each ``backbone-backbone`` link as an order-independent
    ``edge_key`` pair; ``access`` holds each ``access-backbone`` link as
    ``(access_id, backbone_id)``. ``removed_backbone`` holds the ``backbone-backbone``
    pairs the operator pruned from the mesh, also as ``edge_key`` pairs.
    ``required_backbone`` are the operator-forced backbone ids restricted to the
    eligible set; it is empty until the search plan refines it.
    """

    backbone: frozenset[tuple[str, str]] = frozenset()
    access: frozenset[tuple[str, str]] = frozenset()
    removed_backbone: frozenset[tuple[str, str]] = frozenset()
    required_backbone: frozenset[str] = frozenset()

@dataclass(frozen=True)
class RoleOverrides:
    """Operator role pins resolved from PoP names to concrete vertex ids.

    ``forced_backbone_ids`` are the ids fixed into the backbone tier;
    ``prohibited_backbone_ids`` are barred from it. ``forced_links`` carries the
    operator's pinned edges resolved to ids.
    """

    forced_backbone_ids: frozenset[str] = frozenset()
    prohibited_backbone_ids: frozenset[str] = frozenset()
    forced_links: ForcedLinks = field(default_factory=ForcedLinks)

@dataclass(frozen=True)
class DesignInputs:
    """Pre-computed vertex, edge, and shortest-path context shared across backbone sets."""

    access_vertices: list[Vertex]
    carrier_pops: list[Vertex]
    physical_edges: dict[tuple[str, str], PhysicalEdge]
    eligible_backbone_ids: set[str]
    adjacency: dict[str, list[tuple[str, float]]]
    all_distances: dict[str, dict[str, float]]
    all_predecessors: dict[str, dict[str, str]]
    # Each carrier PoP's non-trivial biconnected blocks (a city may sit in several):
    # backbone nodes can be wired into a city-survivable mesh only when they all share
    # one common block. Subsumes the older 2-edge-component oracle (biconnected ⟹ bridgeless).
    carrier_blocks: dict[str, frozenset[int]]

class ValidationReport(TypedDict):
    """Structured results of validating a design against the hard requirements."""

    connected: bool
    component_count: int
    min_distinct_neighbor_degree: int
    degree_deficient_vertices: list[dict[str, object]]
    biconnected_no_articulation_points: bool
    articulation_points: list[dict[str, str]]
    access_vertices_with_required_backbone_links: bool
    demand_missing_backbone_redundancy: list[dict[str, str]]
    backbone_meets_mesh_link_target: bool
    backbone_mesh_degree_deficient: list[dict[str, object]]
    backbone_mesh_two_edge_connected: bool
    backbone_mesh_two_vertex_connected: bool

@dataclass(frozen=True)
class DesignPaths:
    """All file paths a WAN map's design is computed from.

    ``vertex_files`` pairs each tenant with its per-tenant vertices CSV; the
    tenant is carried here because the CSVs no longer hold a ``tenant`` column.
    ``off_net_path`` is an optional CSV of off-net candidate seats (non-PoP
    locations the operator may force as backbone nodes, reached by local fiber).
    """

    vertex_files: tuple[tuple[str, Path], ...]
    edge_path: Path
    regional_edge_paths: tuple[Path, ...] = ()
    off_net_path: Path | None = None

@dataclass(frozen=True)
class SourceFiles:
    """Input file paths recorded in the JSON output for provenance."""

    vertex_files: tuple[Path, ...]
    edge_path: Path

@dataclass(frozen=True)
class DesignArtifacts:
    """A completed design bundled with the vertices and edges it was built from."""

    vertices: list[Vertex]
    physical_edges: dict[tuple[str, str], PhysicalEdge]
    design: Design
    validation: ValidationReport

KIND_POP = "PoP"
KIND_ROADM = "ROADM"
# Vertex kinds that make a vertex a routable carrier PoP on the backbone graph.
CARRIER_KINDS = frozenset({KIND_POP, KIND_ROADM})

def is_carrier_pop(vertex: Vertex) -> bool:
    """Whether a vertex is a carrier PoP (a routable backbone node)."""
    return vertex.kind in CARRIER_KINDS

def backbone_city_allowed(
    info: VertexInfo,
    datacenter_cities: frozenset[tuple[str, str]],
    restrict: bool = True,
) -> bool:
    """Whether a vertex's city passes the data-center backbone gate.

    The gate restricts backbone placement to cities where a colocation provider operates
    a cage. When ``restrict`` is ``False`` (the operator's free-for-all, i.e.
    ``restrict_backbone_to_datacenters`` off) the gate is open and every city passes.
    """
    return not restrict or (info.municipality, info.state) in datacenter_cities
