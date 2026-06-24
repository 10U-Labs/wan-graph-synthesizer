"""The synthesizer's design vocabulary: tiers, tuning, routing, and validation.

These types build on the input-graph types in ``synthesizer.input_graph``
(``Vertex`` / ``PhysicalEdge`` and the geographic helpers); everything here is the
synthesizer's own in-memory representation, layered on top of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from synthesizer.input_graph import PhysicalEdge, Vertex


@dataclass(frozen=True)
class AccessEdge:
    """A logical link from an access vertex to a chosen aggregation PoP."""

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
    """A complete three-tier design: tier assignments, edges, routes, metrics."""

    core_ids: tuple[str, ...]
    aggregation_ids: tuple[str, ...]
    transit_ids: tuple[str, ...]
    access_edges: list[AccessEdge]
    physical_edge_keys: set[tuple[str, str]]
    path_uses: list[PathUse]
    metrics: DesignMetrics

@dataclass(frozen=True)
class EnumBudget:
    """Memory budget governing how many core sets the search may enumerate."""

    memory_fraction: float = 0.6  # share of RAM the core enumeration may use
    set_peak_bytes: int = 160  # peak bytes one enumerated core set costs


@dataclass(frozen=True)
class ClusterTuning:
    """Dials for scale-adaptive (mutual k-NN) clustering of access vertices.

    Mirrored as function-argument defaults in ``clustering.py`` (which ``model``
    cannot import without a cycle), so keep the two in step.
    """

    min_points: int = 2  # access vertices needed to seed a new aggregation
    radius_miles: tuple[float, float] = (50.0, 250.0)  # (fallback floor, bridge-guard ceiling)
    k: int | None = None  # mutual-neighbor count; None -> min_points


@dataclass(frozen=True)
class Tuning:
    """Algorithm dials plus the three required redundancy degrees.

    The three degrees are operator requirements the design must meet, each its own
    REST resource (``core-mesh-degree`` / ``aggregation-homing-degree`` /
    ``access-homing-degree``) with no default at the config layer; the values here
    are construction fallbacks only. ``core_links_per_core`` is how many other cores
    each core links to on the backbone; ``aggregation_homing_degree`` is how many
    cores each aggregation homes to; ``access_aggregation_links`` is how many
    aggregations each access vertex homes to. The remaining fields are the algorithm
    dials exposed together as the ``knobs`` resource.
    """

    cluster: ClusterTuning = field(default_factory=ClusterTuning)  # access-vertex clustering dials
    compass_octants: int = 8  # compass sectors used to score a core's link spread
    core_links_per_core: int = 3  # other cores each core wires to (core-mesh-degree)
    aggregation_homing_degree: int = 2  # cores each aggregation homes to
    core_coverage_target_miles: float = 600.0  # grow cores until every aggregation is this near one
    access_aggregation_links: int = 2  # aggregations each access vertex homes to
    enum_budget: EnumBudget = field(default_factory=EnumBudget)  # core-enumeration memory budget

# The three edge types a forced connection may pin, named as in ``README.md``.
FORCED_CONNECTION_TYPES = frozenset({"core-core", "aggregation-core", "access-aggregation"})

@dataclass(frozen=True)
class ForcedConnection:
    """An operator-pinned edge between two named PoPs of a given edge type.

    ``edge_type`` is one of :data:`FORCED_CONNECTION_TYPES`; ``source`` and
    ``target`` are PoP display names (resolved to vertex ids by the overrides
    layer, like ``forced_core_names``). The endpoints must already be seated in
    the tiers the edge type requires (e.g. both cores for ``core-core``).
    """

    edge_type: str
    source: str
    target: str

@dataclass(frozen=True)
class RoleExclusions:
    """Operator pins that bar a PoP from a tier, by PoP display name.

    ``prohibited_core_names`` bar a PoP from the core tier; ``prohibited_aggregation_names``
    bar it from the aggregation tier. The two bars are independent -- a PoP barred from one
    can still take the other; a PoP barred from both is excluded entirely. The overrides
    layer resolves both to vertex ids. (There is no "access" bar: access is inherent to
    non-PoP demand, not a tier the synthesizer assigns to a carrier PoP.)
    """

    prohibited_core_names: tuple[str, ...] = ()
    prohibited_aggregation_names: tuple[str, ...] = ()

@dataclass(frozen=True)
class DesignParams:
    """Operator choices plus the algorithm :class:`Tuning` for the synthesis."""

    min_core_count: int = 3  # minimum cores; the search adds more only if needed
    max_core_count: int | None = None  # ceiling on cores; None leaves the tier uncapped
    forced_core_names: tuple[str, ...] = ()  # PoPs pinned as cores by the operator
    forced_aggregation_names: tuple[str, ...] = ()  # PoPs pinned as aggregations
    exclusions: RoleExclusions = field(default_factory=RoleExclusions)  # role bars
    tuning: Tuning = field(default_factory=Tuning)

@dataclass(frozen=True)
class ForcedLinks:
    """Operator-forced edges (and core pins) resolved to vertex ids.

    ``core`` holds each ``core-core`` link as an order-independent
    ``edge_key`` pair; ``aggregation`` holds each ``aggregation-core``
    link as ``(aggregation_id, core_id)``; ``access`` holds each ``access-aggregation``
    link as ``(access_id, aggregation_id)``. ``removed_core`` holds the ``core-core``
    pairs the operator pruned from the core backbone, also as ``edge_key`` pairs.
    ``required_cores`` are the operator-forced core ids restricted to the eligible set;
    it is empty until the search plan refines it.
    """

    core: frozenset[tuple[str, str]] = frozenset()
    aggregation: frozenset[tuple[str, str]] = frozenset()
    access: frozenset[tuple[str, str]] = frozenset()
    removed_core: frozenset[tuple[str, str]] = frozenset()
    required_cores: frozenset[str] = frozenset()

@dataclass(frozen=True)
class RoleOverrides:
    """Operator role pins resolved from PoP names to concrete vertex ids.

    ``forced_core_ids`` and ``forced_aggregation_ids`` are the ids fixed into
    the core and aggregation tiers; a PoP pinned as both is co-located and has
    already been split into a distinct ``CORE`` vertex (kept here) and ``AGGR``
    vertex (whose id is what lands in ``forced_aggregation_ids``). ``prohibited_core_ids``
    are barred from the core tier; ``prohibited_aggregation_ids`` are barred from the
    aggregation tier (no free aggregation and no co-located twin). The two bars are
    independent; a PoP in both is excluded entirely.

    A forced installation is realized as a co-located carrier twin before pins are
    resolved, so its force-pin lands in ``forced_aggregation_ids`` like any other.
    ``forced_links`` carries the operator's pinned edges resolved to ids.
    """

    forced_core_ids: frozenset[str] = frozenset()
    forced_aggregation_ids: frozenset[str] = frozenset()
    prohibited_core_ids: frozenset[str] = frozenset()
    prohibited_aggregation_ids: frozenset[str] = frozenset()
    forced_links: ForcedLinks = field(default_factory=ForcedLinks)

@dataclass(frozen=True)
class DesignInputs:
    """Pre-computed vertex, edge, and shortest-path context shared across cores."""

    access_vertices: list[Vertex]
    carrier_pops: list[Vertex]
    physical_edges: dict[tuple[str, str], PhysicalEdge]
    eligible_aggregation_ids: set[str]
    adjacency: dict[str, list[tuple[str, float]]]
    all_distances: dict[str, dict[str, float]]
    all_predecessors: dict[str, dict[str, str]]

class ValidationReport(TypedDict):
    """Structured results of validating a design against the hard requirements."""

    connected: bool
    component_count: int
    min_distinct_neighbor_degree: int
    degree_deficient_vertices: list[dict[str, object]]
    biconnected_no_articulation_points: bool
    articulation_points: list[dict[str, str]]
    access_vertices_with_required_aggregation_links: bool
    aggregations_dual_homed_to_cores: bool
    aggregations_missing_core_redundancy: list[dict[str, str]]
    cores_meet_backbone_link_target: bool
    core_backbone_degree_deficient: list[dict[str, object]]
    core_backbone_two_edge_connected: bool

@dataclass(frozen=True)
class DesignPaths:
    """All file paths a WAN map's design is computed from.

    ``vertex_files`` pairs each tenant with its per-tenant vertices CSV; the
    tenant is carried here because the CSVs no longer hold a ``tenant`` column.
    ``off_net_path`` is an optional CSV of off-net candidate seats (non-PoP
    locations the operator may force as cores/aggregations, reached by local fiber).
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
