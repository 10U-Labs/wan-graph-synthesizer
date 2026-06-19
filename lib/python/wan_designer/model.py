"""Data model and primitive helpers for the WAN designer."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict


KML_NS = {"k": "http://www.opengis.net/kml/2.2"}

EARTH_RADIUS_MILES = 3958.7613

@dataclass(frozen=True)
class VertexInfo:
    """Descriptive, non-structural attributes of a vertex.

    ``description`` is free-text source provenance; ``municipality`` and ``state``
    are the serving city and 2-letter U.S. state shown in the map tooltip (carrier
    PoPs derive these from their ``City, ST`` name). ``justified_aggregation`` marks
    an access site (e.g. a military installation) the operator has justified as an
    aggregation point; it is read from the ``Justified as an aggregation point``
    vertex column and is meaningless for carrier PoPs.
    """

    description: str = ""
    municipality: str = ""
    state: str = ""
    justified_aggregation: bool = False

@dataclass(frozen=True)
class Vertex:
    """A geographic vertex: an access site, a cloud region, or a carrier PoP.

    ``tenant`` is the operator or program the vertex belongs to (e.g. ``Lumen``,
    ``F-35``, ``AWS``, ``DCN``); ``kind`` is the facility type (``PoP``,
    ``ROADM``, ``Military installation``, ``CSP data center``, ``UARC``,
    ``Corporate office``). Carrier PoPs are the vertices whose ``kind`` is in
    :data:`CARRIER_KINDS`; everything else is an access/demand vertex.
    """

    id: str
    name: str
    tenant: str
    kind: str
    coords: tuple[float, float]  # (latitude, longitude)
    # Descriptive (non-structural) attributes: source notes plus the serving
    # municipality and 2-letter state shown in the map tooltip.
    info: VertexInfo = field(default_factory=VertexInfo)
    # Whether the vertex appears on the source mapbook layer (carrier PoPs are
    # backbone infrastructure and are not shown; installations and regions are).
    shown_in_map: bool = True

    @property
    def lat(self) -> float:
        """Latitude in degrees."""
        return self.coords[0]

    @property
    def lon(self) -> float:
        """Longitude in degrees."""
        return self.coords[1]

@dataclass(frozen=True)
class PhysicalEdge:
    """A physical Carrier mapbook link between two PoPs."""

    source: str
    target: str
    distance_miles: float
    source_page: str = ""
    note: str = ""

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
    """Mileage totals and the optimization score for a design."""

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


# Every core must link to at least this many other cores. The single source of
# truth shared by validation (the floor it checks) and the backbone (the floor a
# ``core_backbone_max_degree`` thinning must hold each core at).
CORE_BACKBONE_MIN_DEGREE = 3


@dataclass(frozen=True)
class Tuning:
    """Algorithm dials for the optimizer.

    These defaults are the single source of truth; ``etc/joint.yml`` overrides
    them. The clustering defaults are mirrored as function-argument defaults in
    ``clustering.py`` (which ``model`` cannot import without a cycle), so keep the
    two in step. ``core_backbone_min_degree`` and ``access_aggregation_links`` are
    the two minimum-connectivity requirements the design must meet (per core, and
    per access vertex). ``core_backbone_max_degree`` is the optional opposite: a
    ceiling that thins the full core mesh (``None`` leaves it uncapped).
    """

    cluster_min_points: int = 2  # access vertices needed to seed a new aggregation
    cluster_radius_miles: tuple[float, float] = (50.0, 250.0)  # (floor, ceiling) on derived radius
    compass_octants: int = 8  # compass sectors used to score a core's link spread
    core_backbone_min_degree: int = CORE_BACKBONE_MIN_DEGREE  # min backbone links per core
    core_backbone_max_degree: int | None = None  # cap on backbone links per core (None: uncapped)
    core_coverage_target_miles: float = 600.0  # grow cores until every aggregation is this near one
    access_aggregation_links: int = 2  # aggregation facilities each access vertex homes to
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
    """Operator pins that bar a PoP from a role, by PoP display name.

    ``excluded_names`` bar a PoP from every selected role (core, aggregation, and
    access home); ``prohibited_aggregation_names`` bar it from the aggregation tier
    only -- it stays eligible to be a core. The overrides layer resolves both to
    vertex ids.
    """

    excluded_names: tuple[str, ...] = ()
    prohibited_aggregation_names: tuple[str, ...] = ()

@dataclass(frozen=True)
class DesignParams:
    """Operator choices plus the algorithm :class:`Tuning` for the optimization."""

    min_core_count: int = 3  # minimum cores; the search adds more only if needed
    max_core_count: int | None = None  # ceiling on cores; None leaves the tier uncapped
    allow_roadm_aggregation: bool = False
    forced_core_names: tuple[str, ...] = ()  # PoPs pinned as cores by the operator
    forced_aggregation_names: tuple[str, ...] = ()  # PoPs pinned as aggregations
    exclusions: RoleExclusions = field(default_factory=RoleExclusions)  # role bars
    tuning: Tuning = field(default_factory=Tuning)

@dataclass(frozen=True)
class ForcedLinks:
    """Operator-forced edges (and core pins) resolved to vertex ids.

    ``core`` holds each ``core-core`` link as an order-independent :func:`edge_key`
    pair; ``aggregation`` holds each ``aggregation-core`` link as
    ``(aggregation_id, core_id)``; ``access`` holds each ``access-aggregation`` link
    as ``(access_id, aggregation_id)``. ``removed_core`` holds the ``core-core``
    pairs the operator pruned from the otherwise-full core mesh, also as
    :func:`edge_key` pairs. ``required_cores`` are the operator-forced core ids
    restricted to the eligible set; it is empty until the search plan refines it.
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
    vertex (whose id is what lands in ``forced_aggregation_ids``). ``excluded_ids``
    are barred from being a core, an aggregation, or an access home;
    ``prohibited_aggregation_ids`` are barred from the aggregation tier only (no free
    aggregation and no co-located twin) yet stay eligible to be a core.

    A forced installation is realized as a co-located carrier twin before pins are
    resolved, so its force-pin lands in ``forced_aggregation_ids`` like any other.
    ``forced_links`` carries the operator's pinned edges resolved to ids.
    """

    forced_core_ids: frozenset[str] = frozenset()
    forced_aggregation_ids: frozenset[str] = frozenset()
    excluded_ids: frozenset[str] = frozenset()
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
    cores_full_mesh: bool
    core_pairs_disconnected: list[dict[str, str]]
    core_backbone_min_degree: int
    core_backbone_max_degree: int
    cores_connect_to_three_others: bool
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

def slugify(value: str) -> str:
    """Normalize a string into a lowercase underscore-separated id slug."""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "vertex"

KIND_POP = "PoP"
KIND_ROADM = "ROADM"
# Vertex kinds that make a vertex a routable carrier PoP on the backbone graph.
CARRIER_KINDS = frozenset({KIND_POP, KIND_ROADM})

def is_carrier_pop(vertex: Vertex) -> bool:
    """Whether a vertex is a carrier PoP (a routable backbone node)."""
    return vertex.kind in CARRIER_KINDS

def is_justified_aggregation(vertex: Vertex) -> bool:
    """Whether an access vertex is operator-justified as an aggregation point.

    Carrier PoPs are excluded: the justification flag governs which non-carrier
    access sites (military installations and the like) the operator wants to stand
    up as aggregation facilities, so it never applies to backbone PoPs.
    """
    return not is_carrier_pop(vertex) and vertex.info.justified_aggregation

def carrier_role(vertex: Vertex) -> str:
    """The optimizer role of a carrier PoP: transit-only ROADMs are ``roadm``."""
    return "roadm" if vertex.kind == KIND_ROADM else "aggregator"

def edge_key(left: str, right: str) -> tuple[str, str]:
    """Return the two PoP ids as an order-independent edge key."""
    if left == right:
        raise ValueError(f"Self-loop is not a valid Carrier edge: {left}")
    return (left, right) if left < right else (right, left)

def haversine_miles(a: Vertex, b: Vertex) -> float:
    """Great-circle distance between two vertices in miles."""
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    delta_lat = math.radians(b.lat - a.lat)
    delta_lon = math.radians(b.lon - a.lon)
    sin_lat = math.sin(delta_lat / 2.0)
    sin_lon = math.sin(delta_lon / 2.0)
    value = sin_lat * sin_lat + math.cos(lat1) * math.cos(lat2) * sin_lon * sin_lon
    return 2.0 * EARTH_RADIUS_MILES * math.asin(math.sqrt(value))
