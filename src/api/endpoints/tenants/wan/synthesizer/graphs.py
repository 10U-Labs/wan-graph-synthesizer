"""Graph algorithms: shortest paths, vertex-disjoint routing, connectivity."""

from __future__ import annotations

import heapq
import math
from collections import deque
from dataclasses import dataclass

from synthesizer.input_graph import PhysicalEdge, edge_key


def dijkstra(
    adjacency: dict[str, list[tuple[str, float]]], source: str
) -> tuple[dict[str, float], dict[str, str]]:
    """Shortest-path distances and predecessors from a single source."""
    distances = {source: 0.0}
    predecessors: dict[str, str] = {}
    queue = [(0.0, source)]

    while queue:
        distance, vertex_id = heapq.heappop(queue)
        if distance > distances[vertex_id] + 1e-9:
            continue
        for neighbor, weight in adjacency.get(vertex_id, []):
            new_distance = distance + weight
            if new_distance + 1e-9 < distances.get(neighbor, math.inf):
                distances[neighbor] = new_distance
                predecessors[neighbor] = vertex_id
                heapq.heappush(queue, (new_distance, neighbor))

    return distances, predecessors

def reconstruct_path(source: str, target: str, predecessors: dict[str, str]) -> tuple[str, ...]:
    """Rebuild the vertex path from source to target via the predecessor map."""
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
    """Return the set of edge keys traversed by a vertex path."""
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
        vertex = queue.popleft()
        in_queue[vertex] = False
        for edge_index in graph[vertex]:
            edge = edges[edge_index]
            if edge.capacity - edge.flow <= 1e-9:
                continue
            candidate = distance[vertex] + edge.cost
            if candidate + 1e-9 < distance[edge.head]:
                distance[edge.head] = candidate
                parent_edge[edge.head] = edge_index
                if not in_queue[edge.head]:
                    queue.append(edge.head)
                    in_queue[edge.head] = True

    if math.isinf(distance[sink]):
        return False

    vertex = sink
    while vertex != source:
        edge_index = parent_edge[vertex]
        edges[edge_index].flow += 1.0
        edges[edge_index ^ 1].flow -= 1.0
        vertex = edges[edge_index ^ 1].head
    return True

@dataclass
class _FlowNetwork:
    graph: list[list[int]]
    edges: list[_FlowEdge]
    vertex_ids: list[str]
    flow_source: int
    sink: int

def _build_disjoint_flow_network(
    adjacency: dict[str, list[tuple[str, float]]],
    source: str,
    core_set: set[str],
    required: set[str],
    bias: float,
) -> _FlowNetwork:
    """Build the vertex-split min-cost flow network used for disjoint routing.

    Every vertex is split into an in/out pair with unit capacity (vertex-disjoint
    routing); cores are pure sinks behind a super-sink so each carries one path.
    A required core's sink edge carries a ``-bias`` cost (``bias`` exceeds any real
    path mileage), so min-cost flow saturates it whenever a disjoint pair can.
    """
    vertex_ids = sorted(adjacency)
    index = {vertex_id: position for position, vertex_id in enumerate(vertex_ids)}
    sink = 2 * len(vertex_ids)
    graph: list[list[int]] = [[] for _ in range(sink + 1)]
    edges: list[_FlowEdge] = []

    def add_edge(tail: int, head: int, capacity: float, cost: float) -> None:
        graph[tail].append(len(edges))
        edges.append(_FlowEdge(head, capacity, cost))
        graph[head].append(len(edges))
        edges.append(_FlowEdge(tail, 0.0, -cost))

    for vertex_id in vertex_ids:
        if vertex_id != source:
            add_edge(2 * index[vertex_id], 2 * index[vertex_id] + 1, 1.0, 0.0)
    for vertex_id in vertex_ids:
        if vertex_id in core_set:
            continue
        for neighbor, distance in adjacency[vertex_id]:
            add_edge(2 * index[vertex_id] + 1, 2 * index[neighbor], 1.0, distance)
    for core in sorted(core_set):
        add_edge(2 * index[core] + 1, sink, 1.0, -bias if core in required else 0.0)

    return _FlowNetwork(graph, edges, vertex_ids, 2 * index[source] + 1, sink)

def _trace_flow_paths(network: _FlowNetwork, count: int) -> list[tuple[str, ...]]:
    """Decompose the integral unit flow into `count` vertex sequences."""
    # Forward edges occupy even indices; their tail is the paired reverse head.
    used: dict[int, list[int]] = {}
    for index in range(0, len(network.edges), 2):
        edge = network.edges[index]
        if edge.flow > 0.5:
            tail = network.edges[index + 1].head
            used.setdefault(tail, []).append(edge.head)

    source = network.vertex_ids[network.flow_source // 2]
    paths: list[tuple[str, ...]] = []
    for _ in range(count):
        sequence = [source]
        vertex = network.flow_source
        while True:
            nxt = used[vertex].pop()
            if nxt == network.sink:
                break
            if nxt % 2 == 0:
                sequence.append(network.vertex_ids[nxt // 2])
            vertex = nxt
        paths.append(tuple(sequence))

    paths.sort(key=lambda path: path[-1])
    return paths

def _paths_distance(
    paths: list[tuple[str, ...]],
    adjacency: dict[str, list[tuple[str, float]]],
) -> float:
    weight: dict[tuple[str, str], float] = {}
    for vertex_id, neighbors in adjacency.items():
        for neighbor, distance in neighbors:
            weight[(vertex_id, neighbor)] = distance
    total = 0.0
    for path in paths:
        for index in range(len(path) - 1):
            total += weight[(path[index], path[index + 1])]
    return total

def vertex_disjoint_paths_to_cores(
    adjacency: dict[str, list[tuple[str, float]]],
    source: str,
    core_ids: tuple[str, ...],
    count: int = 2,
    required_cores: frozenset[str] = frozenset(),
) -> tuple[float, list[tuple[str, ...]]]:
    """Return `count` vertex-disjoint shortest paths from `source` to distinct cores.

    Routing is over the physical `adjacency` graph. Each vertex has unit capacity
    (vertex splitting), so the returned paths share only `source`; each terminates
    at a different core and the combined distance is minimized. Every core in
    ``required_cores`` is forced to anchor one of the returned paths. Returns
    ``(math.inf, [])`` when fewer than `count` such paths exist, or when a required
    core cannot anchor a path in any disjoint solution.
    """
    core_set = {core for core in core_ids if core != source}
    if count < 1 or len(core_set) < count or source not in adjacency:
        return math.inf, []
    if not required_cores <= core_set:
        return math.inf, []

    bias = sum(weight for neighbors in adjacency.values() for _, weight in neighbors) + 1.0
    network = _build_disjoint_flow_network(adjacency, source, core_set, set(required_cores), bias)
    pushed = 0
    while pushed < count and _spfa_augment(
        network.graph, network.edges, network.flow_source, network.sink
    ):
        pushed += 1
    if pushed < count:
        return math.inf, []

    paths = _trace_flow_paths(network, count)
    if not required_cores <= {path[-1] for path in paths}:
        return math.inf, []
    return _paths_distance(paths, adjacency), paths

def undirected_adjacency(
    vertex_ids: set[str], edges: set[tuple[str, str]]
) -> dict[str, set[str]]:
    """Build an undirected neighbor map restricted to the given vertex ids."""
    adjacency: dict[str, set[str]] = {vertex_id: set() for vertex_id in vertex_ids}
    for left, right in edges:
        if left in adjacency and right in adjacency:
            adjacency[left].add(right)
            adjacency[right].add(left)
    return adjacency

def connected_components(vertex_ids: set[str], edges: set[tuple[str, str]]) -> list[list[str]]:
    """Return the connected components of the design graph as sorted id lists."""
    adjacency = undirected_adjacency(vertex_ids, edges)
    remaining = set(adjacency)
    components: list[list[str]] = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        queue: deque[str] = deque([start])
        component: list[str] = []
        while queue:
            vertex_id = queue.popleft()
            component.append(vertex_id)
            for neighbor in sorted(adjacency[vertex_id]):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
        components.append(sorted(component))
    return components

def is_two_edge_connected(vertex_ids: set[str], edges: set[tuple[str, str]]) -> bool:
    """True if the graph is connected and survives the loss of any single edge.

    A graph is 2-edge-connected when it is connected and bridgeless. Vertex sets
    here are tiny (a handful of cores), so each edge is probed by removal rather
    than via a linear-time bridge search.
    """
    if len(connected_components(vertex_ids, edges)) != 1:
        return False
    return all(
        len(connected_components(vertex_ids, edges - {edge})) == 1 for edge in edges
    )

def articulation_points(vertex_ids: set[str], edges: set[tuple[str, str]]) -> set[str]:
    """Return cut vertices whose removal would disconnect the design graph."""
    adjacency = undirected_adjacency(vertex_ids, edges)
    visited: set[str] = set()
    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    points: set[str] = set()
    time = 0

    def dfs(vertex_id: str) -> None:
        nonlocal time
        visited.add(vertex_id)
        discovery[vertex_id] = time
        low[vertex_id] = time
        time += 1
        children = 0

        for neighbor in sorted(adjacency[vertex_id]):
            if neighbor not in visited:
                parent[neighbor] = vertex_id
                children += 1
                dfs(neighbor)
                low[vertex_id] = min(low[vertex_id], low[neighbor])
                if parent.get(vertex_id) is None and children > 1:
                    points.add(vertex_id)
                if parent.get(vertex_id) is not None and low[neighbor] >= discovery[vertex_id]:
                    points.add(vertex_id)
            elif neighbor != parent.get(vertex_id):
                low[vertex_id] = min(low[vertex_id], discovery[neighbor])

    for vertex_id in sorted(adjacency):
        if vertex_id not in visited:
            parent[vertex_id] = None
            dfs(vertex_id)

    return points


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
