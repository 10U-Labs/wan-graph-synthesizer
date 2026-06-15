"""Data model and primitive helpers for the WAN designer."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict


KML_NS = {"k": "http://www.opengis.net/kml/2.2"}

EARTH_RADIUS_MILES = 3958.7613

@dataclass(frozen=True)
class Node:
    """A geographic placemark: an access site or a Carrier PoP."""

    id: str
    name: str
    category: str
    kind: str
    lat: float
    lon: float
    description: str = ""

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
    """A logical link from an access node to a chosen aggregation PoP."""

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
class DesignParams:
    """Tuning knobs for the three-tier optimization."""

    core_count: int = 3  # minimum number of cores; more are added if worthwhile
    allow_roadm_aggregation: bool = False
    core_coverage_improvement: float = 0.10  # min traffic-to-core cut to add a core
    forced_core_names: tuple[str, ...] = ()  # PoPs pinned as cores by the operator
    forced_aggregation_names: tuple[str, ...] = ()  # PoPs pinned as aggregations
    excluded_names: tuple[str, ...] = ()  # PoPs barred from every selected role

@dataclass(frozen=True)
class RoleOverrides:
    """Operator role pins resolved from PoP names to concrete node ids.

    ``forced_core_ids`` and ``forced_aggregation_ids`` are the ids fixed into
    the core and aggregation tiers; a PoP pinned as both is co-located and has
    already been split into a distinct ``CORE`` node (kept here) and ``AGGR``
    node (whose id is what lands in ``forced_aggregation_ids``). ``excluded_ids``
    are barred from being a core, an aggregation, or an access home.
    """

    forced_core_ids: frozenset[str] = frozenset()
    forced_aggregation_ids: frozenset[str] = frozenset()
    excluded_ids: frozenset[str] = frozenset()

@dataclass(frozen=True)
class DesignInputs:
    """Pre-computed node, edge, and shortest-path context shared across cores."""

    access_nodes: list[Node]
    carrier_pops: list[Node]
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
    degree_deficient_nodes: list[dict[str, object]]
    biconnected_no_articulation_points: bool
    articulation_points: list[dict[str, str]]
    access_nodes_with_two_aggregation_links: bool
    aggregations_dual_homed_to_cores: bool
    aggregations_missing_core_redundancy: list[dict[str, str]]
    cores_full_mesh: bool
    core_pairs_disconnected: list[dict[str, str]]

@dataclass(frozen=True)
class CliPaths:
    """All file paths resolved from the command line."""

    input_path: Path
    edge_path: Path
    role_path: Path | None
    mapbook_pdf: Path | None
    output_dir: Path
    regional_node_path: Path | None = None
    regional_edge_paths: tuple[Path, ...] = ()

@dataclass(frozen=True)
class SourceFiles:
    """Input file paths recorded in the JSON output for provenance."""

    input_path: Path
    edge_path: Path
    mapbook_pdf: Path | None

@dataclass(frozen=True)
class DesignArtifacts:
    """A completed design bundled with the nodes and edges it was built from."""

    nodes: list[Node]
    physical_edges: dict[tuple[str, str], PhysicalEdge]
    design: Design
    validation: ValidationReport

def slugify(value: str) -> str:
    """Normalize a string into a lowercase underscore-separated id slug."""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "node"

def classify_category(category: str) -> str:
    """Map a folder/category label to a canonical node kind."""
    normalized = category.lower()
    if "carrier" in normalized and "pop" in normalized:
        return "carrier_pop"
    if "sentinel" in normalized:
        return "sentinel"
    if "cui" in normalized:
        return "cui_region"
    if "top secret" in normalized:
        return "ts_region"
    if "secret" in normalized or "cloud service" in normalized:
        return "csp_secret"
    if "f-35" in normalized or "f35" in normalized:
        return "f35"
    return slugify(category)

def edge_key(left: str, right: str) -> tuple[str, str]:
    """Return the two PoP ids as an order-independent edge key."""
    if left == right:
        raise ValueError(f"Self-loop is not a valid Carrier edge: {left}")
    return (left, right) if left < right else (right, left)

def haversine_miles(a: Node, b: Node) -> float:
    """Great-circle distance between two nodes in miles."""
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    delta_lat = math.radians(b.lat - a.lat)
    delta_lon = math.radians(b.lon - a.lon)
    sin_lat = math.sin(delta_lat / 2.0)
    sin_lon = math.sin(delta_lon / 2.0)
    value = sin_lat * sin_lat + math.cos(lat1) * math.cos(lat2) * sin_lon * sin_lon
    return 2.0 * EARTH_RADIUS_MILES * math.asin(math.sqrt(value))
