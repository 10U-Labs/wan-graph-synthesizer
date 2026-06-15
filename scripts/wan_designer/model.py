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
    description: str = ""
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
class Tuning:
    """Algorithm dials for the optimizer.

    These defaults are the single source of truth; ``etc/config.yml`` overrides
    them. The clustering defaults are mirrored as function-argument defaults in
    ``clustering.py`` (which ``model`` cannot import without a cycle), so keep the
    two in step.
    """

    cluster_min_points: int = 2  # access vertices needed to seed a new aggregation
    cluster_min_radius_miles: float = 50.0  # floor on the derived cluster radius
    cluster_max_radius_miles: float = 250.0  # ceiling on the derived cluster radius
    compass_octants: int = 8  # compass sectors used to score a core's link spread
    enum_memory_fraction: float = 0.6  # share of RAM the core enumeration may use
    core_set_peak_bytes: int = 160  # peak bytes one enumerated core set costs

@dataclass(frozen=True)
class DesignParams:
    """Operator choices plus the algorithm :class:`Tuning` for the optimization."""

    core_count: int = 3  # exact number of cores in the design
    allow_roadm_aggregation: bool = False
    forced_core_names: tuple[str, ...] = ()  # PoPs pinned as cores by the operator
    forced_aggregation_names: tuple[str, ...] = ()  # PoPs pinned as aggregations
    excluded_names: tuple[str, ...] = ()  # PoPs barred from every selected role
    tuning: Tuning = field(default_factory=Tuning)

@dataclass(frozen=True)
class RoleOverrides:
    """Operator role pins resolved from PoP names to concrete vertex ids.

    ``forced_core_ids`` and ``forced_aggregation_ids`` are the ids fixed into
    the core and aggregation tiers; a PoP pinned as both is co-located and has
    already been split into a distinct ``CORE`` vertex (kept here) and ``AGGR``
    vertex (whose id is what lands in ``forced_aggregation_ids``). ``excluded_ids``
    are barred from being a core, an aggregation, or an access home.
    """

    forced_core_ids: frozenset[str] = frozenset()
    forced_aggregation_ids: frozenset[str] = frozenset()
    excluded_ids: frozenset[str] = frozenset()

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
    access_vertices_with_two_aggregation_links: bool
    aggregations_dual_homed_to_cores: bool
    aggregations_missing_core_redundancy: list[dict[str, str]]
    cores_full_mesh: bool
    core_pairs_disconnected: list[dict[str, str]]

@dataclass(frozen=True)
class CliPaths:
    """All file paths resolved from the command line."""

    vertices_path: Path
    edge_path: Path
    mapbook_pdf: Path | None
    output_dir: Path
    regional_edge_paths: tuple[Path, ...] = ()

@dataclass(frozen=True)
class SourceFiles:
    """Input file paths recorded in the JSON output for provenance."""

    vertices_path: Path
    edge_path: Path
    mapbook_pdf: Path | None

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
