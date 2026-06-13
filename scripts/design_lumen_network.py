#!/usr/bin/env python3
"""
Compute a three-tier WAN design over the Lumen mapbook graph.

Inputs:
* KMZ/KML point data for F-35, Sentinel, CSP Secret regions, and Lumen PoPs.
* A CSV edge list derived from the Lumen mapbook PDF route lines.
* Optional PoP roles from the mapbook legend. NGO aggregators are eligible for
  core/aggregation roles; ROADMs are kept as transit nodes by default.

Design model:
* Access tier: every F-35, Sentinel, and CSP Secret node is an access node.
* Aggregation tier: selected Lumen PoPs. Each access node connects to two
  distinct aggregation PoPs.
* Core tier: at most three selected Lumen PoPs. Each aggregation PoP is routed
  to two distinct core PoPs over the physical Lumen edge graph.
* Transit: any Lumen PoP that appears on a selected physical path but is not a
  core or aggregation point.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import html
import itertools
import json
import math
import re
import sys
import zipfile
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TypedDict
from xml.etree import ElementTree as ET


KML_NS = {"k": "http://www.opengis.net/kml/2.2"}
EARTH_RADIUS_MILES = 3958.7613


@dataclass(frozen=True)
class Node:
    """A geographic placemark: an access site or a Lumen PoP."""

    id: str
    name: str
    category: str
    kind: str
    lat: float
    lon: float
    description: str = ""


@dataclass(frozen=True)
class PhysicalEdge:
    """A physical Lumen mapbook link between two PoPs."""

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

    core_count: int = 3
    core_candidate_limit: int = 32
    min_core_separation_miles: float = 750.0
    aggregation_candidates_per_access: int = 8
    aggregation_penalty_miles: float = 40.0
    upper_tier_weight: float = 0.15
    allow_roadm_aggregation: bool = False


@dataclass(frozen=True)
class DesignInputs:
    """Pre-computed node, edge, and shortest-path context shared across cores."""

    access_nodes: list[Node]
    lumen_pops: list[Node]
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
    if "lumen" in normalized and "pop" in normalized:
        return "lumen_pop"
    if "sentinel" in normalized:
        return "sentinel"
    if "secret" in normalized or "cloud service" in normalized:
        return "csp_secret"
    if "f-35" in normalized or "f35" in normalized:
        return "f35"
    return slugify(category)


def edge_key(left: str, right: str) -> tuple[str, str]:
    """Return the two PoP ids as an order-independent edge key."""
    if left == right:
        raise ValueError(f"Self-loop is not a valid Lumen edge: {left}")
    return (left, right) if left < right else (right, left)


def read_kml_root(input_path: Path) -> ET.Element:
    """Parse the root KML element from a .kmz or .kml file."""
    if input_path.suffix.lower() == ".kmz":
        with zipfile.ZipFile(input_path) as archive:
            kml_names = [name for name in archive.namelist() if name.lower().endswith(".kml")]
            if not kml_names:
                raise ValueError(f"{input_path} does not contain a .kml file")
            preferred = "doc.kml" if "doc.kml" in kml_names else kml_names[0]
            return ET.fromstring(archive.read(preferred))
    if input_path.suffix.lower() == ".kml":
        return ET.parse(input_path).getroot()
    raise ValueError(f"Unsupported input type: {input_path}. Expected .kmz or .kml")


def clean_description(raw_text: str | None) -> str:
    """Strip HTML markup from a placemark description into plain text."""
    if not raw_text:
        return ""
    text = html.unescape(raw_text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def parse_point_placemark(placemark: ET.Element, category: str, used_ids: set[str]) -> Node | None:
    """Parse one point placemark into a Node, or None if it has no point."""
    coordinates = placemark.find(".//k:Point/k:coordinates", KML_NS)
    if coordinates is None or not coordinates.text or not coordinates.text.strip():
        return None

    lon_text, lat_text, *_ = coordinates.text.strip().split(",")
    name = placemark.findtext("k:name", default="Unnamed", namespaces=KML_NS).strip()
    kind = classify_category(category)
    base_id = f"{kind}_{slugify(name)}"
    node_id = base_id
    suffix = 2
    while node_id in used_ids:
        node_id = f"{base_id}_{suffix}"
        suffix += 1
    used_ids.add(node_id)

    return Node(
        id=node_id,
        name=name,
        category=category,
        kind=kind,
        lat=float(lat_text),
        lon=float(lon_text),
        description=clean_description(
            placemark.findtext("k:description", default="", namespaces=KML_NS)
        ),
    )


def load_nodes(input_path: Path) -> list[Node]:
    """Load every point placemark from the KMZ/KML as a list of nodes."""
    root = read_kml_root(input_path)
    document = root.find("k:Document", KML_NS)
    if document is None:
        raise ValueError("KML document does not contain a Document element")

    document_name = document.findtext(
        "k:name", default="Top Level Placemarks", namespaces=KML_NS
    ).strip()
    nodes: list[Node] = []
    used_ids: set[str] = set()

    for placemark in document.findall("k:Placemark", KML_NS):
        node = parse_point_placemark(placemark, document_name, used_ids)
        if node is not None:
            nodes.append(node)

    for folder in document.findall("k:Folder", KML_NS):
        category = folder.findtext("k:name", default="Folder", namespaces=KML_NS).strip()
        for placemark in folder.findall("k:Placemark", KML_NS):
            node = parse_point_placemark(placemark, category, used_ids)
            if node is not None:
                nodes.append(node)

    return nodes


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


def load_pop_roles(path: Path | None, lumen_pops: list[Node]) -> dict[str, str]:
    """Load optional Lumen PoP roles, defaulting every PoP to aggregator."""
    roles = {pop.id: "aggregator" for pop in lumen_pops}
    if path is None or not path.exists():
        return roles

    by_name = {pop.name.lower(): pop for pop in lumen_pops}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = row["name"].strip().lower()
            role = row["role"].strip().lower()
            if name not in by_name:
                raise ValueError(f"PoP role file references unknown Lumen PoP: {row['name']}")
            roles[by_name[name].id] = role
    return roles


def load_lumen_edges(path: Path, lumen_pops: list[Node]) -> dict[tuple[str, str], PhysicalEdge]:
    """Load the physical Lumen edge graph from the mapbook-derived CSV."""
    if not path.exists():
        raise ValueError(f"Lumen edge file does not exist: {path}")

    by_name = {pop.name.lower(): pop for pop in lumen_pops}
    by_id = {pop.id: pop for pop in lumen_pops}
    edges: dict[tuple[str, str], PhysicalEdge] = {}

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source_name = row["source"].strip().lower()
            target_name = row["target"].strip().lower()
            if source_name not in by_name:
                raise ValueError(f"Edge file references unknown source PoP: {row['source']}")
            if target_name not in by_name:
                raise ValueError(f"Edge file references unknown target PoP: {row['target']}")

            source = by_name[source_name]
            target = by_name[target_name]
            key = edge_key(source.id, target.id)
            if row.get("distance_miles"):
                distance = float(row["distance_miles"])
            else:
                distance = haversine_miles(source, target)
            edges[key] = PhysicalEdge(
                source=key[0],
                target=key[1],
                distance_miles=distance,
                source_page=row.get("source_page", ""),
                note=row.get("note", ""),
            )

    unknown_ids = {node_id for pair in edges for node_id in pair} - set(by_id)
    if unknown_ids:
        raise ValueError(f"Internal edge loading error for IDs: {sorted(unknown_ids)}")
    return edges


def build_adjacency(
    edges: dict[tuple[str, str], PhysicalEdge],
) -> dict[str, list[tuple[str, float]]]:
    """Build a sorted weighted adjacency map from the physical edges."""
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for (left, right), edge in edges.items():
        adjacency.setdefault(left, []).append((right, edge.distance_miles))
        adjacency.setdefault(right, []).append((left, edge.distance_miles))
    for neighbors in adjacency.values():
        neighbors.sort()
    return adjacency


def dijkstra(
    adjacency: dict[str, list[tuple[str, float]]], source: str
) -> tuple[dict[str, float], dict[str, str]]:
    """Shortest-path distances and predecessors from a single source."""
    distances = {source: 0.0}
    predecessors: dict[str, str] = {}
    queue = [(0.0, source)]

    while queue:
        distance, node_id = heapq.heappop(queue)
        if distance > distances[node_id] + 1e-9:
            continue
        for neighbor, weight in adjacency.get(node_id, []):
            new_distance = distance + weight
            if new_distance + 1e-9 < distances.get(neighbor, math.inf):
                distances[neighbor] = new_distance
                predecessors[neighbor] = node_id
                heapq.heappush(queue, (new_distance, neighbor))

    return distances, predecessors


def reconstruct_path(source: str, target: str, predecessors: dict[str, str]) -> tuple[str, ...]:
    """Rebuild the node path from source to target via the predecessor map."""
    if source == target:
        return (source,)
    if target not in predecessors:
        return ()
    path = [target]
    while path[-1] != source:
        current = path[-1]
        if current not in predecessors:
            return ()
        path.append(predecessors[current])
    path.reverse()
    return tuple(path)


def path_edge_keys(path: tuple[str, ...]) -> set[tuple[str, str]]:
    """Return the set of edge keys traversed by a node path."""
    return {edge_key(path[index], path[index + 1]) for index in range(len(path) - 1)}


@dataclass
class _FlowEdge:
    head: int
    capacity: float
    cost: float
    flow: float = 0.0


def _spfa_augment(
    graph: list[list[int]],
    edges: list[_FlowEdge],
    source: int,
    sink: int,
) -> bool:
    """Push one unit of flow along the minimum-cost residual path.

    Uses SPFA (queue-based Bellman-Ford) because residual reverse edges carry
    negative cost. Returns True if an augmenting path was found.
    """
    distance = [math.inf] * len(graph)
    parent_edge = [-1] * len(graph)
    in_queue = [False] * len(graph)
    distance[source] = 0.0
    queue: deque[int] = deque([source])
    in_queue[source] = True

    while queue:
        node = queue.popleft()
        in_queue[node] = False
        for edge_index in graph[node]:
            edge = edges[edge_index]
            if edge.capacity - edge.flow <= 1e-9:
                continue
            candidate = distance[node] + edge.cost
            if candidate + 1e-9 < distance[edge.head]:
                distance[edge.head] = candidate
                parent_edge[edge.head] = edge_index
                if not in_queue[edge.head]:
                    queue.append(edge.head)
                    in_queue[edge.head] = True

    if math.isinf(distance[sink]):
        return False

    node = sink
    while node != source:
        edge_index = parent_edge[node]
        edges[edge_index].flow += 1.0
        edges[edge_index ^ 1].flow -= 1.0
        node = edges[edge_index ^ 1].head
    return True


@dataclass
class _FlowNetwork:
    graph: list[list[int]]
    edges: list[_FlowEdge]
    node_ids: list[str]
    flow_source: int
    sink: int


def _build_disjoint_flow_network(
    adjacency: dict[str, list[tuple[str, float]]],
    source: str,
    core_set: set[str],
) -> _FlowNetwork:
    """Build the node-split min-cost flow network used for disjoint routing.

    Every node is split into an in/out pair with unit capacity (node-disjoint
    routing); cores are pure sinks behind a super-sink so each carries one path.
    """
    node_ids = sorted(adjacency)
    index = {node_id: position for position, node_id in enumerate(node_ids)}
    sink = 2 * len(node_ids)
    graph: list[list[int]] = [[] for _ in range(sink + 1)]
    edges: list[_FlowEdge] = []

    def add_edge(tail: int, head: int, capacity: float, cost: float) -> None:
        graph[tail].append(len(edges))
        edges.append(_FlowEdge(head, capacity, cost))
        graph[head].append(len(edges))
        edges.append(_FlowEdge(tail, 0.0, -cost))

    for node_id in node_ids:
        if node_id != source:
            add_edge(2 * index[node_id], 2 * index[node_id] + 1, 1.0, 0.0)
    for node_id in node_ids:
        if node_id in core_set:
            continue
        for neighbor, distance in adjacency[node_id]:
            add_edge(2 * index[node_id] + 1, 2 * index[neighbor], 1.0, distance)
    for core in sorted(core_set):
        add_edge(2 * index[core] + 1, sink, 1.0, 0.0)

    return _FlowNetwork(graph, edges, node_ids, 2 * index[source] + 1, sink)


def _trace_flow_paths(network: _FlowNetwork, count: int) -> list[tuple[str, ...]]:
    """Decompose the integral unit flow into `count` node sequences."""
    # Forward edges occupy even indices; their tail is the paired reverse head.
    used: dict[int, list[int]] = {}
    for index in range(0, len(network.edges), 2):
        edge = network.edges[index]
        if edge.flow > 0.5:
            tail = network.edges[index + 1].head
            used.setdefault(tail, []).append(edge.head)

    source = network.node_ids[network.flow_source // 2]
    paths: list[tuple[str, ...]] = []
    for _ in range(count):
        sequence = [source]
        vertex = network.flow_source
        while True:
            nxt = used[vertex].pop()
            if nxt == network.sink:
                break
            if nxt % 2 == 0:
                sequence.append(network.node_ids[nxt // 2])
            vertex = nxt
        paths.append(tuple(sequence))

    paths.sort(key=lambda path: path[-1])
    return paths


def _paths_distance(
    paths: list[tuple[str, ...]],
    adjacency: dict[str, list[tuple[str, float]]],
) -> float:
    weight: dict[tuple[str, str], float] = {}
    for node_id, neighbors in adjacency.items():
        for neighbor, distance in neighbors:
            weight[(node_id, neighbor)] = distance
    total = 0.0
    for path in paths:
        for index in range(len(path) - 1):
            total += weight[(path[index], path[index + 1])]
    return total


def node_disjoint_paths_to_cores(
    adjacency: dict[str, list[tuple[str, float]]],
    source: str,
    core_ids: tuple[str, ...],
    count: int = 2,
) -> tuple[float, list[tuple[str, ...]]]:
    """Return `count` node-disjoint shortest paths from `source` to distinct cores.

    Routing is over the physical `adjacency` graph. Each node has unit capacity
    (node splitting), so the returned paths share only `source`; each terminates
    at a different core and the combined distance is minimized. Returns
    ``(math.inf, [])`` when fewer than `count` such paths exist.
    """
    core_set = {core for core in core_ids if core != source}
    if count < 1 or len(core_set) < count or source not in adjacency:
        return math.inf, []

    network = _build_disjoint_flow_network(adjacency, source, core_set)
    pushed = 0
    while pushed < count and _spfa_augment(
        network.graph, network.edges, network.flow_source, network.sink
    ):
        pushed += 1
    if pushed < count:
        return math.inf, []

    paths = _trace_flow_paths(network, count)
    return _paths_distance(paths, adjacency), paths


def undirected_adjacency(
    node_ids: set[str], edges: set[tuple[str, str]]
) -> dict[str, set[str]]:
    """Build an undirected neighbor map restricted to the given node ids."""
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for left, right in edges:
        if left in adjacency and right in adjacency:
            adjacency[left].add(right)
            adjacency[right].add(left)
    return adjacency


def connected_components(node_ids: set[str], edges: set[tuple[str, str]]) -> list[list[str]]:
    """Return the connected components of the design graph as sorted id lists."""
    adjacency = undirected_adjacency(node_ids, edges)
    remaining = set(adjacency)
    components: list[list[str]] = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        queue: deque[str] = deque([start])
        component: list[str] = []
        while queue:
            node_id = queue.popleft()
            component.append(node_id)
            for neighbor in sorted(adjacency[node_id]):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
        components.append(sorted(component))
    return components


def articulation_points(node_ids: set[str], edges: set[tuple[str, str]]) -> set[str]:
    """Return cut vertices whose removal would disconnect the design graph."""
    adjacency = undirected_adjacency(node_ids, edges)
    visited: set[str] = set()
    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    points: set[str] = set()
    time = 0

    def dfs(node_id: str) -> None:
        nonlocal time
        visited.add(node_id)
        discovery[node_id] = time
        low[node_id] = time
        time += 1
        children = 0

        for neighbor in sorted(adjacency[node_id]):
            if neighbor not in visited:
                parent[neighbor] = node_id
                children += 1
                dfs(neighbor)
                low[node_id] = min(low[node_id], low[neighbor])
                if parent.get(node_id) is None and children > 1:
                    points.add(node_id)
                if parent.get(node_id) is not None and low[neighbor] >= discovery[node_id]:
                    points.add(node_id)
            elif neighbor != parent.get(node_id):
                low[node_id] = min(low[node_id], discovery[neighbor])

    for node_id in sorted(adjacency):
        if node_id not in visited:
            parent[node_id] = None
            dfs(node_id)

    return points


def choose_core_candidates(
    access_nodes: list[Node],
    lumen_pops: list[Node],
    eligible_ids: set[str],
    all_distances: dict[str, dict[str, float]],
    limit: int,
) -> list[str]:
    """Rank eligible PoPs as core candidates by graph and access centrality."""
    by_id = {node.id: node for node in lumen_pops}
    scored: list[tuple[float, str]] = []
    for pop_id in eligible_ids:
        pop = by_id[pop_id]
        graph_distances = all_distances[pop_id]
        reachable_distances = [
            distance for node_id, distance in graph_distances.items() if node_id != pop_id
        ]
        if not reachable_distances:
            continue
        graph_score = sum(reachable_distances) / len(reachable_distances)
        access_score = sum(
            haversine_miles(access, pop) for access in access_nodes
        ) / len(access_nodes)
        scored.append((graph_score + access_score, pop_id))
    scored.sort()
    return [pop_id for _score, pop_id in scored[:limit]]


def aggregation_core_paths(
    aggregation_id: str,
    core_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> tuple[float, list[PathUse]]:
    """Route an aggregation to two distinct cores over node-disjoint paths.

    Returns the total path distance and one ``aggregation_to_core`` PathUse per
    core, or ``(math.inf, [])`` if two node-disjoint paths to two distinct cores
    do not exist over the physical graph.
    """
    total, paths = node_disjoint_paths_to_cores(adjacency, aggregation_id, core_ids, 2)
    if not paths:
        return math.inf, []
    uses = [
        PathUse(
            "aggregation_to_core",
            aggregation_id,
            path[-1],
            path,
            sum(
                physical_edges[edge_key(path[index], path[index + 1])].distance_miles
                for index in range(len(path) - 1)
            ),
        )
        for path in paths
    ]
    return total, uses


def core_mesh_paths(
    core_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    all_predecessors: dict[str, dict[str, str]],
) -> list[PathUse]:
    """Route a shortest path between every pair of cores (the full mesh)."""
    uses: list[PathUse] = []
    for left, right in itertools.combinations(core_ids, 2):
        distance = all_distances[left].get(right, math.inf)
        if not math.isfinite(distance):
            return []
        path = reconstruct_path(left, right, all_predecessors[left])
        if len(path) < 2:
            return []
        uses.append(PathUse("core_mesh", left, right, path, distance))
    return uses


@dataclass
class _DesignDraft:
    access_edges: list[AccessEdge]
    selected_aggregation_ids: set[str]
    path_uses: list[PathUse]


def aggregation_core_map(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
) -> dict[str, tuple[float, list[PathUse]]]:
    """Map each eligible aggregation to its node-disjoint routing to two cores."""
    allowed = sorted(inputs.eligible_aggregation_ids - set(core_ids))
    feasible: dict[str, tuple[float, list[PathUse]]] = {}
    for aggregation_id in allowed:
        cost, paths = aggregation_core_paths(
            aggregation_id, core_ids, inputs.adjacency, inputs.physical_edges
        )
        if math.isfinite(cost):
            feasible[aggregation_id] = (cost, paths)
    return feasible


def best_aggregation_pair(
    access: Node,
    aggregation_core: dict[str, tuple[float, list[PathUse]]],
    by_id: dict[str, Node],
    params: DesignParams,
) -> tuple[tuple[float, str], tuple[float, str]] | None:
    """Pick the cheapest pair of aggregations to dual-home one access node."""
    ranked = sorted(
        (
            (haversine_miles(access, by_id[aggregation_id]), aggregation_id)
            for aggregation_id in aggregation_core
        ),
        key=lambda item: (item[0], item[1]),
    )[: params.aggregation_candidates_per_access]
    best_cost = math.inf
    chosen: tuple[tuple[float, str], tuple[float, str]] | None = None
    for left, right in itertools.combinations(ranked, 2):
        pair_cost = (
            left[0]
            + right[0]
            + params.upper_tier_weight
            * (aggregation_core[left[1]][0] + aggregation_core[right[1]][0])
        )
        if pair_cost < best_cost:
            best_cost = pair_cost
            chosen = (left, right)
    return chosen


def finalize_design(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    params: DesignParams,
    draft: _DesignDraft,
) -> Design:
    """Compute edge sets, mileage, and score for a completed design draft."""
    physical_edge_keys: set[tuple[str, str]] = set()
    for path_use in draft.path_uses:
        physical_edge_keys.update(path_edge_keys(path_use.path))

    access_miles = sum(edge.distance_miles for edge in draft.access_edges)
    physical_miles = sum(
        inputs.physical_edges[key].distance_miles for key in physical_edge_keys
    )
    score = (
        access_miles
        + physical_miles
        + params.aggregation_penalty_miles * len(draft.selected_aggregation_ids)
    )
    lumen_on_paths = {node_id for use in draft.path_uses for node_id in use.path}
    transit_ids = tuple(
        sorted(lumen_on_paths - set(core_ids) - draft.selected_aggregation_ids)
    )
    return Design(
        core_ids=core_ids,
        aggregation_ids=tuple(sorted(draft.selected_aggregation_ids)),
        transit_ids=transit_ids,
        access_edges=draft.access_edges,
        physical_edge_keys=physical_edge_keys,
        path_uses=draft.path_uses,
        metrics=DesignMetrics(score, access_miles, physical_miles),
    )


def build_design_for_cores(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    params: DesignParams,
) -> Design | None:
    """Assemble a full three-tier design for one fixed set of core PoPs."""
    aggregation_core = aggregation_core_map(core_ids, inputs)
    if len(aggregation_core) < 2:
        return None

    by_id = {node.id: node for node in inputs.lumen_pops}
    access_edges: list[AccessEdge] = []
    selected: set[str] = set()
    for access in inputs.access_nodes:
        chosen = best_aggregation_pair(access, aggregation_core, by_id, params)
        if chosen is None:
            return None
        for distance, aggregation_id in chosen:
            access_edges.append(AccessEdge(access.id, aggregation_id, distance))
            selected.add(aggregation_id)

    path_uses = core_mesh_paths(core_ids, inputs.all_distances, inputs.all_predecessors)
    if not path_uses:
        return None
    for aggregation_id in sorted(selected):
        path_uses.extend(aggregation_core[aggregation_id][1])

    draft = _DesignDraft(access_edges, selected, path_uses)
    return finalize_design(core_ids, inputs, params, draft)


def compute_eligible_ids(
    lumen_pops: list[Node],
    roles: dict[str, str],
    adjacency: dict[str, list[tuple[str, float]]],
    allow_roadm_aggregation: bool,
) -> set[str]:
    """Lumen PoPs that may serve as core or aggregation nodes.

    A PoP needs at least two physical links to ever be dual-homed to two cores,
    so degree-one PoPs (spurs) are excluded regardless of their mapbook role.
    """
    return {
        pop.id
        for pop in lumen_pops
        if (allow_roadm_aggregation or roles.get(pop.id, "aggregator") == "aggregator")
        and len(adjacency.get(pop.id, [])) >= 2
    }


def all_pairs_shortest(
    lumen_pops: list[Node],
    adjacency: dict[str, list[tuple[str, float]]],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, str]]]:
    """Run Dijkstra from every Lumen PoP for reuse across core combinations."""
    all_distances: dict[str, dict[str, float]] = {}
    all_predecessors: dict[str, dict[str, str]] = {}
    for pop in lumen_pops:
        all_distances[pop.id], all_predecessors[pop.id] = dijkstra(adjacency, pop.id)
    return all_distances, all_predecessors


def validate_pop_graph(
    lumen_pops: list[Node],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    adjacency: dict[str, list[tuple[str, float]]],
) -> None:
    """Raise if the physical edge graph and Lumen PoP set are inconsistent."""
    pop_ids = {pop.id for pop in lumen_pops}
    physical_node_ids = {node_id for edge in physical_edges for node_id in edge}
    if not pop_ids.issuperset(physical_node_ids):
        raise ValueError("Physical edge graph references unknown Lumen PoP IDs")
    missing_pops = sorted(pop_ids - set(adjacency))
    if missing_pops:
        names = ", ".join(node.name for node in lumen_pops if node.id in missing_pops)
        raise ValueError(f"Lumen PoPs missing from physical edge graph: {names}")


def cores_too_close(
    core_ids: tuple[str, ...],
    pop_by_id: dict[str, Node],
    min_separation_miles: float,
) -> bool:
    """True if any pair of candidate cores is closer than the separation floor."""
    return any(
        haversine_miles(pop_by_id[left], pop_by_id[right]) < min_separation_miles
        for left, right in itertools.combinations(core_ids, 2)
    )


def scored_design(nodes: list[Node], design: Design) -> Design:
    """Add large penalties for any violated hard requirement to the score."""
    validation = validate_design(nodes, design)
    penalties = (
        validation["min_distinct_neighbor_degree"] < 2,
        not validation["connected"],
        not validation["aggregations_dual_homed_to_cores"],
        not validation["cores_full_mesh"],
    )
    design.metrics.score += 1_000_000.0 * sum(1 for failed in penalties if failed)
    return design


def search_best_design(
    nodes: list[Node],
    inputs: DesignInputs,
    params: DesignParams,
    core_candidates: list[str],
) -> Design:
    """Search core combinations for the lowest-scoring feasible design."""
    pop_by_id = {pop.id: pop for pop in inputs.lumen_pops}
    best: Design | None = None
    checked = 0
    for core_ids in itertools.combinations(core_candidates, params.core_count):
        if cores_too_close(core_ids, pop_by_id, params.min_core_separation_miles):
            continue
        checked += 1
        design = build_design_for_cores(tuple(core_ids), inputs, params)
        if design is None:
            continue
        design = scored_design(nodes, design)
        if best is None or design.metrics.score < best.metrics.score:
            best = design
    if best is None:
        raise ValueError(f"No feasible three-tier design found after {checked} core sets")
    return best


def optimize_three_tier_design(
    nodes: list[Node],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    roles: dict[str, str],
    params: DesignParams,
) -> Design:
    """Optimize a three-tier WAN over the Lumen graph for the given parameters."""
    if params.core_count < 2 or params.core_count > 3:
        raise ValueError("core_count must be 2 or 3")

    access_nodes = [node for node in nodes if node.kind != "lumen_pop"]
    lumen_pops = [node for node in nodes if node.kind == "lumen_pop"]
    adjacency = build_adjacency(physical_edges)
    validate_pop_graph(lumen_pops, physical_edges, adjacency)
    all_distances, all_predecessors = all_pairs_shortest(lumen_pops, adjacency)

    eligible_ids = compute_eligible_ids(
        lumen_pops, roles, adjacency, params.allow_roadm_aggregation
    )
    if len(eligible_ids) < max(2, params.core_count):
        raise ValueError("Not enough eligible Lumen aggregation/core PoPs")

    inputs = DesignInputs(
        access_nodes=access_nodes,
        lumen_pops=lumen_pops,
        physical_edges=physical_edges,
        eligible_aggregation_ids=eligible_ids,
        adjacency=adjacency,
        all_distances=all_distances,
        all_predecessors=all_predecessors,
    )
    core_candidates = choose_core_candidates(
        access_nodes, lumen_pops, eligible_ids, all_distances, params.core_candidate_limit
    )
    if len(core_candidates) < params.core_count:
        raise ValueError("Not enough reachable core candidates")

    return search_best_design(nodes, inputs, params, core_candidates)


def design_edge_set(design: Design) -> set[tuple[str, str]]:
    """All edges in the design: selected physical edges plus access edges."""
    edges = set(design.physical_edge_keys)
    edges.update(edge_key(edge.source, edge.target) for edge in design.access_edges)
    return edges


def included_node_ids(design: Design) -> set[str]:
    """Every node id that participates in the design."""
    ids = set(design.core_ids) | set(design.aggregation_ids) | set(design.transit_ids)
    ids.update(node_id for edge in design.physical_edge_keys for node_id in edge)
    ids.update(edge.source for edge in design.access_edges)
    ids.update(edge.target for edge in design.access_edges)
    return ids


def design_badness(nodes: list[Node], design: Design) -> tuple[int, int, int]:
    """Disconnection, articulation, and degree-deficit counts as a sort key."""
    validation = validate_design(nodes, design)
    return (
        0 if validation["connected"] else validation["component_count"],
        len(validation["articulation_points"]),
        len(validation["degree_deficient_nodes"]),
    )


def with_updated_physical_edges(
    design: Design,
    physical_edge_keys: set[tuple[str, str]],
) -> Design:
    """Copy a design with a new physical edge set and refreshed transit tier."""
    lumen_on_physical = {node_id for edge in physical_edge_keys for node_id in edge}
    transit_ids = tuple(
        sorted(lumen_on_physical - set(design.core_ids) - set(design.aggregation_ids))
    )
    return Design(
        core_ids=design.core_ids,
        aggregation_ids=design.aggregation_ids,
        transit_ids=transit_ids,
        access_edges=design.access_edges,
        physical_edge_keys=physical_edge_keys,
        path_uses=design.path_uses,
        metrics=DesignMetrics(
            design.metrics.score,
            design.metrics.access_miles,
            design.metrics.physical_miles,
        ),
    )


def refresh_physical_costs(
    physical_edges: dict[tuple[str, str], PhysicalEdge], design: Design
) -> Design:
    """Recompute physical mileage and score after the edge set changed."""
    design.metrics.physical_miles = sum(
        physical_edges[key].distance_miles for key in design.physical_edge_keys
    )
    design.metrics.score = design.metrics.access_miles + design.metrics.physical_miles
    return design


def best_edge_to_add(
    nodes: list[Node],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    current: Design,
    current_badness: tuple[int, int, int],
) -> tuple[tuple[str, str] | None, tuple[int, int, int]]:
    """Find the unused physical edge that most reduces design badness."""
    best_key: tuple[str, str] | None = None
    best_rank: tuple[int, int, int, float, tuple[str, str]] | None = None
    best_badness = current_badness
    for key, edge in physical_edges.items():
        if key in current.physical_edge_keys:
            continue
        candidate = with_updated_physical_edges(
            current, current.physical_edge_keys | {key}
        )
        candidate_badness = design_badness(nodes, candidate)
        if candidate_badness >= current_badness:
            continue
        gain = tuple(
            before - after for before, after in zip(current_badness, candidate_badness)
        )
        rank = (-gain[0], -gain[1], -gain[2], edge.distance_miles, key)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best_key = key
            best_badness = candidate_badness
    return best_key, best_badness


def augment_physical_resilience(
    nodes: list[Node],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    design: Design,
) -> Design:
    """Greedily add physical edges to remove cut vertices and degree deficits."""
    current = with_updated_physical_edges(design, set(design.physical_edge_keys))
    current_badness = design_badness(nodes, current)

    while current_badness != (0, 0, 0):
        best_key, best_badness = best_edge_to_add(
            nodes, physical_edges, current, current_badness
        )
        if best_key is None:
            break
        current = with_updated_physical_edges(
            current, current.physical_edge_keys | {best_key}
        )
        current_badness = best_badness

    return refresh_physical_costs(physical_edges, current)


def selected_physical_adjacency(design: Design) -> dict[str, list[tuple[str, float]]]:
    """Unit-weight adjacency over only the physical edges the design selected."""
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for left, right in design.physical_edge_keys:
        adjacency.setdefault(left, []).append((right, 1.0))
        adjacency.setdefault(right, []).append((left, 1.0))
    return adjacency


def aggregations_without_core_redundancy(design: Design) -> list[str]:
    """Aggregations lacking two node-disjoint paths to two distinct cores."""
    adjacency = selected_physical_adjacency(design)
    missing: list[str] = []
    for aggregation_id in design.aggregation_ids:
        _distance, paths = node_disjoint_paths_to_cores(
            adjacency, aggregation_id, design.core_ids, 2
        )
        if len(paths) < 2:
            missing.append(aggregation_id)
    return missing


def disconnected_core_pairs(design: Design) -> list[tuple[str, str]]:
    """Core pairs that are not connected over the selected physical edges."""
    adjacency = selected_physical_adjacency(design)
    disconnected: list[tuple[str, str]] = []
    for left, right in itertools.combinations(design.core_ids, 2):
        if left not in adjacency:
            disconnected.append((left, right))
            continue
        distances, _predecessors = dijkstra(adjacency, left)
        if right not in distances:
            disconnected.append((left, right))
    return disconnected


def neighbor_degrees(
    ids: set[str], edges: set[tuple[str, str]]
) -> dict[str, int]:
    """Distinct-neighbor degree of every included node in the design graph."""
    neighbors: dict[str, set[str]] = {node_id: set() for node_id in ids}
    for left, right in edges:
        if left in ids and right in ids:
            neighbors[left].add(right)
            neighbors[right].add(left)
    return {node_id: len(value) for node_id, value in neighbors.items()}


def access_attachment_counts(design: Design) -> dict[str, int]:
    """Number of aggregation links attached to each access node."""
    counts: dict[str, int] = {}
    for edge in design.access_edges:
        counts[edge.source] = counts.get(edge.source, 0) + 1
    return counts


def validate_design(nodes: list[Node], design: Design) -> ValidationReport:
    """Check a design against every hard structural requirement."""
    nodes_by_id = {node.id: node for node in nodes}
    ids = included_node_ids(design)
    edges = design_edge_set(design)
    components = connected_components(ids, edges)
    degrees = neighbor_degrees(ids, edges)
    articulations = articulation_points(ids, edges) if len(components) == 1 else set()
    attachments = access_attachment_counts(design)
    missing_core_redundancy = aggregations_without_core_redundancy(design)
    core_pairs = disconnected_core_pairs(design)

    return {
        "connected": len(components) == 1,
        "component_count": len(components),
        "min_distinct_neighbor_degree": min(degrees.values()) if degrees else 0,
        "degree_deficient_nodes": [
            {"id": node_id, "name": nodes_by_id[node_id].name, "degree": degree}
            for node_id, degree in sorted(degrees.items())
            if degree < 2
        ],
        "biconnected_no_articulation_points": len(components) == 1 and not articulations,
        "articulation_points": [
            {"id": node_id, "name": nodes_by_id[node_id].name}
            for node_id in sorted(articulations)
        ],
        "access_nodes_with_two_aggregation_links": all(
            count == 2 for count in attachments.values()
        ),
        "aggregations_dual_homed_to_cores": not missing_core_redundancy,
        "aggregations_missing_core_redundancy": [
            {"id": node_id, "name": nodes_by_id[node_id].name}
            for node_id in missing_core_redundancy
        ],
        "cores_full_mesh": not core_pairs,
        "core_pairs_disconnected": [
            {"source": nodes_by_id[left].name, "target": nodes_by_id[right].name}
            for left, right in core_pairs
        ],
    }


def node_role(node_id: str, design: Design, node: Node) -> str:
    """Return the tier role (access/core/aggregation/transit/unused) of a node."""
    if node.kind != "lumen_pop":
        return "access"
    if node_id in design.core_ids:
        return "core"
    if node_id in design.aggregation_ids:
        return "aggregation"
    if node_id in design.transit_ids:
        return "transit"
    return "unused"


def sorted_physical_edges(design: Design) -> list[tuple[str, str]]:
    """Return the design's physical edge keys in sorted order."""
    return sorted(design.physical_edge_keys)


def write_json(
    output_path: Path,
    sources: SourceFiles,
    artifacts: DesignArtifacts,
) -> None:
    """Write the full design, nodes, edges, and validation report as JSON."""
    nodes = artifacts.nodes
    physical_edges = artifacts.physical_edges
    design = artifacts.design
    validation = artifacts.validation
    nodes_by_id = {node.id: node for node in nodes}
    payload = {
        "input_file": str(sources.input_path),
        "physical_edge_file": str(sources.edge_path),
        "mapbook_pdf": str(sources.mapbook_pdf) if sources.mapbook_pdf else None,
        "objective": (
            "Three-tier WAN design: access nodes dual-home to Lumen aggregation PoPs, "
            "aggregation PoPs dual-home to core PoPs over the physical Lumen graph, "
            "and the core tier uses at most three nodes."
        ),
        "summary": {
            "core_count": len(design.core_ids),
            "aggregation_count": len(design.aggregation_ids),
            "transit_count": len(design.transit_ids),
            "access_node_count": sum(1 for node in nodes if node.kind != "lumen_pop"),
            "access_edge_count": len(design.access_edges),
            "physical_edge_count": len(design.physical_edge_keys),
            "access_miles": round(design.metrics.access_miles, 3),
            "physical_lumen_miles": round(design.metrics.physical_miles, 3),
            "total_design_miles": round(
                design.metrics.access_miles + design.metrics.physical_miles, 3
            ),
            "score": round(design.metrics.score, 3),
            "cores": [nodes_by_id[node_id].name for node_id in design.core_ids],
            "aggregations": [nodes_by_id[node_id].name for node_id in design.aggregation_ids],
        },
        "validation": validation,
        "nodes": [
            {
                **asdict(node),
                "tier_role": node_role(node.id, design, node),
                "included": node.id in included_node_ids(design),
            }
            for node in nodes
        ],
        "access_edges": [
            {
                "source_id": edge.source,
                "source_name": nodes_by_id[edge.source].name,
                "target_id": edge.target,
                "target_name": nodes_by_id[edge.target].name,
                "edge_kind": "access_to_aggregation",
                "distance_miles": round(edge.distance_miles, 3),
            }
            for edge in sorted(design.access_edges, key=lambda item: (item.source, item.target))
        ],
        "physical_edges": [
            {
                "source_id": left,
                "source_name": nodes_by_id[left].name,
                "target_id": right,
                "target_name": nodes_by_id[right].name,
                "edge_kind": "lumen_physical",
                "distance_miles": round(physical_edges[edge_key(left, right)].distance_miles, 3),
                "source_page": physical_edges[edge_key(left, right)].source_page,
                "note": physical_edges[edge_key(left, right)].note,
            }
            for left, right in sorted_physical_edges(design)
        ],
        "path_uses": [
            {
                "purpose": path_use.purpose,
                "source_id": path_use.source,
                "source_name": nodes_by_id[path_use.source].name,
                "target_id": path_use.target,
                "target_name": nodes_by_id[path_use.target].name,
                "distance_miles": round(path_use.distance_miles, 3),
                "path": [nodes_by_id[node_id].name for node_id in path_use.path],
            }
            for path_use in design.path_uses
        ],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


CSV_FIELDNAMES = [
    "source_id",
    "source_name",
    "source_role",
    "target_id",
    "target_name",
    "target_role",
    "edge_kind",
    "distance_miles",
    "source_page",
]


def csv_edge_row(
    design: Design, source: Node, target: Node, meta: tuple[str, float, str]
) -> dict[str, object]:
    """Build one CSV row for an edge between two nodes."""
    edge_kind, distance, source_page = meta
    return {
        "source_id": source.id,
        "source_name": source.name,
        "source_role": node_role(source.id, design, source),
        "target_id": target.id,
        "target_name": target.name,
        "target_role": node_role(target.id, design, target),
        "edge_kind": edge_kind,
        "distance_miles": round(distance, 3),
        "source_page": source_page,
    }


def write_csv(output_path: Path, artifacts: DesignArtifacts) -> None:
    """Write all selected edges with node roles and distances as CSV."""
    physical_edges = artifacts.physical_edges
    design = artifacts.design
    nodes_by_id = {node.id: node for node in artifacts.nodes}
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for edge in sorted(design.access_edges, key=lambda item: (item.source, item.target)):
            meta = ("access_to_aggregation", edge.distance_miles, "")
            row = csv_edge_row(design, nodes_by_id[edge.source], nodes_by_id[edge.target], meta)
            writer.writerow(row)
        for left, right in sorted_physical_edges(design):
            physical_edge = physical_edges[edge_key(left, right)]
            meta = ("lumen_physical", physical_edge.distance_miles, physical_edge.source_page)
            row = csv_edge_row(design, nodes_by_id[left], nodes_by_id[right], meta)
            writer.writerow(row)


def kml_color_for_role(role: str) -> str:
    """Return the KML ABGR color string for a tier role."""
    return {
        "access": "ff25a8f9",
        "aggregation": "ff00a5ff",
        "core": "ff0000d9",
        "transit": "ff999999",
    }.get(role, "ffffffff")


def write_kml_styles(document: ET.Element) -> None:
    """Append node and edge style definitions to the KML document."""
    circle = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
    for role in ("access", "aggregation", "core", "transit"):
        style = ET.SubElement(document, "Style", id=f"node_{role}")
        icon_style = ET.SubElement(style, "IconStyle")
        ET.SubElement(icon_style, "color").text = kml_color_for_role(role)
        ET.SubElement(icon_style, "scale").text = "1.1" if role == "core" else "0.85"
        ET.SubElement(ET.SubElement(icon_style, "Icon"), "href").text = circle
    for edge_kind, color, width in (("access", "ff25a8f9", "1.4"), ("physical", "ff333333", "2.2")):
        style = ET.SubElement(document, "Style", id=f"edge_{edge_kind}")
        line_style = ET.SubElement(style, "LineStyle")
        ET.SubElement(line_style, "color").text = color
        ET.SubElement(line_style, "width").text = width


def add_kml_line(folder: ET.Element, label: str, style: str, desc: str, ends: str) -> None:
    """Append one styled line-string placemark to a KML folder."""
    placemark = ET.SubElement(folder, "Placemark")
    ET.SubElement(placemark, "name").text = label
    ET.SubElement(placemark, "styleUrl").text = style
    ET.SubElement(placemark, "description").text = desc
    line = ET.SubElement(placemark, "LineString")
    ET.SubElement(line, "tessellate").text = "1"
    ET.SubElement(line, "coordinates").text = ends


def write_kml_nodes(folder: ET.Element, design: Design, nodes: list[Node]) -> None:
    """Append a placemark for every included node to the KML folder."""
    included = included_node_ids(design)
    for node in sorted(
        (node for node in nodes if node.id in included),
        key=lambda item: (node_role(item.id, design, item), item.name),
    ):
        role = node_role(node.id, design, node)
        placemark = ET.SubElement(folder, "Placemark")
        ET.SubElement(placemark, "name").text = node.name
        ET.SubElement(placemark, "styleUrl").text = f"#node_{role}"
        ET.SubElement(placemark, "description").text = f"{role}\n{node.category}\n{node.id}"
        point = ET.SubElement(placemark, "Point")
        ET.SubElement(point, "coordinates").text = f"{node.lon},{node.lat},0"


def kml_edge_specs(artifacts: DesignArtifacts) -> list[tuple[str, str, str, str]]:
    """List (source_id, target_id, style, description) for every selected edge."""
    design = artifacts.design
    specs: list[tuple[str, str, str, str]] = []
    for edge in sorted(design.access_edges, key=lambda item: (item.source, item.target)):
        desc = f"access_to_aggregation\n{edge.distance_miles:.1f} miles"
        specs.append((edge.source, edge.target, "#edge_access", desc))
    for left, right in sorted_physical_edges(design):
        physical_edge = artifacts.physical_edges[edge_key(left, right)]
        miles = f"{physical_edge.distance_miles:.1f} miles"
        desc = f"lumen_physical\n{miles}\n{physical_edge.source_page}"
        specs.append((left, right, "#edge_physical", desc))
    return specs


def write_kml_edges(folder: ET.Element, artifacts: DesignArtifacts) -> None:
    """Append a placemark for every selected access and physical edge."""
    nodes_by_id = {node.id: node for node in artifacts.nodes}
    for source_id, target_id, style, desc in kml_edge_specs(artifacts):
        source, target = nodes_by_id[source_id], nodes_by_id[target_id]
        ends = f"{source.lon},{source.lat},0 {target.lon},{target.lat},0"
        add_kml_line(folder, f"{source.name} to {target.name}", style, desc, ends)


def write_kml(output_path: Path, artifacts: DesignArtifacts) -> None:
    """Write nodes and selected edges as a styled KML map."""
    kml = ET.Element("kml", xmlns=KML_NS["k"])
    document = ET.SubElement(kml, "Document")
    ET.SubElement(document, "name").text = "Three-Tier Lumen WAN Design"
    write_kml_styles(document)

    node_folder = ET.SubElement(document, "Folder")
    ET.SubElement(node_folder, "name").text = "Included Nodes"
    write_kml_nodes(node_folder, artifacts.design, artifacts.nodes)

    edge_folder = ET.SubElement(document, "Folder")
    ET.SubElement(edge_folder, "name").text = "Selected Edges"
    write_kml_edges(edge_folder, artifacts)

    ET.indent(kml, space="  ")
    ET.ElementTree(kml).write(output_path, encoding="utf-8", xml_declaration=True)


def dot_escape(value: str) -> str:
    """Escape a label for safe inclusion in a Graphviz DOT string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_dot(output_path: Path, artifacts: DesignArtifacts) -> None:
    """Write the design as a Graphviz DOT graph colored by tier role."""
    nodes = artifacts.nodes
    physical_edges = artifacts.physical_edges
    design = artifacts.design
    colors = {
        "access": "#f9a825",
        "aggregation": "#00897b",
        "core": "#c62828",
        "transit": "#757575",
    }
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("graph three_tier_lumen_wan_design {\n")
        handle.write('  graph [overlap=false, splines=true];\n')
        handle.write('  node [shape=circle, style=filled, fontname="Helvetica", fontsize=9];\n')
        handle.write('  edge [fontname="Helvetica", fontsize=8];\n')
        included = included_node_ids(design)
        for node in sorted(
            (node for node in nodes if node.id in included), key=lambda item: item.id
        ):
            role = node_role(node.id, design, node)
            handle.write(
                f'  "{node.id}" [label="{dot_escape(node.name)}", '
                f'fillcolor="{colors[role]}", fontcolor="white"];\n'
            )
        for edge in sorted(design.access_edges, key=lambda item: (item.source, item.target)):
            handle.write(
                f'  "{edge.source}" -- "{edge.target}" '
                f'[label="{edge.distance_miles:.0f} mi", color="#f9a825", penwidth=1.1];\n'
            )
        for left, right in sorted_physical_edges(design):
            physical_edge = physical_edges[edge_key(left, right)]
            handle.write(
                f'  "{left}" -- "{right}" '
                f'[label="{physical_edge.distance_miles:.0f} mi", color="#333333", penwidth=2.0];\n'
            )
        handle.write("}\n")


def write_outputs(
    output_dir: Path,
    sources: SourceFiles,
    artifacts: DesignArtifacts,
) -> dict[str, Path]:
    """Write JSON, CSV, KML, and DOT renderings of the design."""
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "json": output_dir / "network_design.json",
        "csv": output_dir / "network_edges.csv",
        "kml": output_dir / "network_design.kml",
        "dot": output_dir / "network_design.dot",
    }
    write_json(outputs["json"], sources, artifacts)
    write_csv(outputs["csv"], artifacts)
    write_kml(outputs["kml"], artifacts)
    write_dot(outputs["dot"], artifacts)
    return outputs


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Compute a three-tier core/aggregation/access WAN over the "
            "Lumen mapbook edge graph."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="f35_sentinel_secret_regions_lumen_400g.kmz",
        help="Input KMZ or KML file. Defaults to the project KMZ.",
    )
    parser.add_argument(
        "--lumen-edges",
        default="data/lumen_edges.csv",
        help="CSV of physical Lumen mapbook route edges.",
    )
    parser.add_argument(
        "--pop-roles",
        default="data/lumen_pop_roles.csv",
        help="Optional CSV of Lumen PoP roles from the mapbook legend.",
    )
    parser.add_argument(
        "--mapbook-pdf",
        default="data/lumen_network_mapbook_2026.pdf",
        help="Optional source PDF path recorded in JSON output.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/lumen_network_design",
        help="Directory for JSON, CSV, KML, and DOT outputs.",
    )
    parser.add_argument(
        "--core-count",
        type=int,
        default=3,
        help="Number of core nodes to select. Must be 2 or 3; default is 3.",
    )
    parser.add_argument(
        "--core-candidate-limit",
        type=int,
        default=32,
        help="Number of best-scored Lumen PoPs to consider as cores.",
    )
    parser.add_argument(
        "--min-core-separation-miles",
        type=float,
        default=750.0,
        help="Minimum great-circle separation between selected core PoPs.",
    )
    parser.add_argument(
        "--aggregation-candidates-per-access",
        type=int,
        default=8,
        help="Nearest eligible aggregation PoPs considered per access node.",
    )
    parser.add_argument(
        "--aggregation-penalty-miles",
        type=float,
        default=40.0,
        help="Facility penalty used to avoid selecting unnecessary aggregation PoPs.",
    )
    parser.add_argument(
        "--upper-tier-weight",
        type=float,
        default=0.15,
        help="How strongly access-to-aggregation choices consider aggregation-to-core distance.",
    )
    parser.add_argument(
        "--allow-roadm-aggregation",
        action="store_true",
        help="Allow mapbook ROADM nodes to be selected as aggregation/core points.",
    )
    parser.add_argument(
        "--no-resilience-augmentation",
        action="store_true",
        help="Do not add extra physical Lumen edges to reduce articulation or degree risk.",
    )
    return parser


def cli_paths(args: argparse.Namespace) -> CliPaths:
    """Resolve command-line arguments into concrete file paths."""
    return CliPaths(
        input_path=Path(args.input),
        edge_path=Path(args.lumen_edges),
        role_path=Path(args.pop_roles) if args.pop_roles else None,
        mapbook_pdf=Path(args.mapbook_pdf) if args.mapbook_pdf else None,
        output_dir=Path(args.output_dir),
    )


def params_from_args(args: argparse.Namespace) -> DesignParams:
    """Build the design parameter bundle from parsed CLI arguments."""
    return DesignParams(
        core_count=args.core_count,
        core_candidate_limit=args.core_candidate_limit,
        min_core_separation_miles=args.min_core_separation_miles,
        aggregation_candidates_per_access=args.aggregation_candidates_per_access,
        aggregation_penalty_miles=args.aggregation_penalty_miles,
        upper_tier_weight=args.upper_tier_weight,
        allow_roadm_aggregation=args.allow_roadm_aggregation,
    )


def run_design(paths: CliPaths, params: DesignParams, augment: bool) -> DesignArtifacts:
    """Load inputs, optimize the design, and validate it."""
    nodes = load_nodes(paths.input_path)
    if not nodes:
        raise ValueError(f"No point placemarks found in {paths.input_path}")
    lumen_pops = [node for node in nodes if node.kind == "lumen_pop"]
    physical_edges = load_lumen_edges(paths.edge_path, lumen_pops)
    roles = load_pop_roles(paths.role_path, lumen_pops)
    design = optimize_three_tier_design(nodes, physical_edges, roles, params)
    if augment:
        design = augment_physical_resilience(nodes, physical_edges, design)
    validation = validate_design(nodes, design)
    return DesignArtifacts(nodes, physical_edges, design, validation)


def print_summary(
    paths: CliPaths, artifacts: DesignArtifacts, outputs: dict[str, Path]
) -> None:
    """Print a human-readable summary of the computed design."""
    design = artifacts.design
    validation = artifacts.validation
    nodes_by_id = {node.id: node for node in artifacts.nodes}
    print(f"Loaded {len(artifacts.nodes)} point nodes from {paths.input_path}")
    print(f"Loaded {len(artifacts.physical_edges)} physical Lumen edges from {paths.edge_path}")
    print(
        f"Selected {len(design.core_ids)} cores, {len(design.aggregation_ids)} "
        f"aggregations, and {len(design.transit_ids)} transit PoPs"
    )
    print("Cores: " + ", ".join(nodes_by_id[node_id].name for node_id in design.core_ids))
    print(
        f"Designed {len(included_node_ids(design))} included nodes and "
        f"{len(design.access_edges) + len(design.physical_edge_keys)} selected edges "
        f"({design.metrics.access_miles + design.metrics.physical_miles:,.1f} total miles)"
    )
    print(
        "Validation: "
        f"connected={validation['connected']}, "
        f"min_degree={validation['min_distinct_neighbor_degree']}, "
        f"access_dual_homed={validation['access_nodes_with_two_aggregation_links']}, "
        f"agg_dual_homed_to_cores={validation['aggregations_dual_homed_to_cores']}, "
        f"cores_full_mesh={validation['cores_full_mesh']}"
    )
    for kind, path in outputs.items():
        print(f"Wrote {kind}: {path}")


def exit_code_for(validation: ValidationReport) -> int:
    """Return a non-zero exit code if any hard requirement was violated."""
    if not validation["aggregations_dual_homed_to_cores"]:
        names = ", ".join(
            entry["name"] for entry in validation["aggregations_missing_core_redundancy"]
        )
        print(
            f"error: aggregations lacking two node-disjoint paths to two cores: {names}",
            file=sys.stderr,
        )
        return 2
    if not validation["cores_full_mesh"]:
        print("error: core tier is not a full mesh", file=sys.stderr)
        return 2
    if validation["degree_deficient_nodes"]:
        print(
            "warning: validation found nodes with fewer than two distinct neighbors",
            file=sys.stderr,
        )
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    """Compute the three-tier WAN design and write all output renderings."""
    args = build_parser().parse_args(argv)
    paths = cli_paths(args)
    params = params_from_args(args)
    mapbook = (
        paths.mapbook_pdf if paths.mapbook_pdf and paths.mapbook_pdf.exists() else None
    )
    sources = SourceFiles(paths.input_path, paths.edge_path, mapbook)
    try:
        artifacts = run_design(paths, params, not args.no_resilience_augmentation)
        outputs = write_outputs(paths.output_dir, sources, artifacts)
    except (ValueError, OSError, ET.ParseError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print_summary(paths, artifacts, outputs)
    return exit_code_for(artifacts.validation)


if __name__ == "__main__":
    raise SystemExit(main())
