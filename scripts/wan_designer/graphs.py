"""Graph algorithms: shortest paths, node-disjoint routing, connectivity."""

from __future__ import annotations

import heapq
import math
from collections import deque
from dataclasses import dataclass

from wan_designer.model import edge_key


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
