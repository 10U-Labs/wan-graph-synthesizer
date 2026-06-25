"""Graph algorithms: shortest paths and connectivity."""

from __future__ import annotations

import heapq
import math
from collections import deque

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

def bridges(vertex_ids: set[str], edges: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """Return the edges whose removal would raise the graph's component count.

    A bridge lies on no cycle, so deleting it splits its component in two. Vertex
    sets here are tiny (a handful of backbone nodes), so each edge is probed by
    removal rather than via a linear-time bridge search.
    """
    base = len(connected_components(vertex_ids, edges))
    return {
        edge
        for edge in edges
        if len(connected_components(vertex_ids, edges - {edge})) > base
    }

def is_two_edge_connected(vertex_ids: set[str], edges: set[tuple[str, str]]) -> bool:
    """True if the graph is connected and survives the loss of any single edge.

    A graph is 2-edge-connected when it is connected and bridgeless.
    """
    if len(connected_components(vertex_ids, edges)) != 1:
        return False
    return not bridges(vertex_ids, edges)

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
