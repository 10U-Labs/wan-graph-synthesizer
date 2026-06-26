"""Graph algorithms: shortest paths and connectivity."""

from __future__ import annotations

import heapq
import math
from collections import deque
from collections.abc import Callable, Iterator

from synthesizer.input_graph import PhysicalEdge, edge_key


def dijkstra(
    adjacency: dict[str, list[tuple[str, float]]],
    source: str,
    blocked: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[dict[str, float], dict[str, str]]:
    """Shortest-path distances and predecessors from a single source.

    ``blocked`` is a set of ``edge_key`` spans the search may not traverse -- used to
    route a detour around a span already carrying backbone traffic.
    """
    distances = {source: 0.0}
    predecessors: dict[str, str] = {}
    queue = [(0.0, source)]

    while queue:
        distance, vertex_id = heapq.heappop(queue)
        if distance > distances[vertex_id] + 1e-9:
            continue
        for neighbor, weight in adjacency.get(vertex_id, []):
            if blocked and edge_key(vertex_id, neighbor) in blocked:
                continue
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

def _lowlink_dfs(
    adjacency: dict[str, list[tuple[str, float]]],
    on_edge: Callable[[str, str], None],
    on_finish: Callable[[str, str, int, int], None],
) -> None:
    """Iterative Tarjan low-link sweep, the shared skeleton of the connectivity passes.

    Calls ``on_edge(u, v)`` for every tree edge and every back edge (to an ancestor), in
    DFS order, and ``on_finish(node, parent, low_node, disc_parent)`` when a node's subtree
    is done -- enough for both the bridge and the biconnected-block sweeps to do their own
    bookkeeping without restating the traversal. Run iteratively (an explicit stack) so a
    long carrier graph cannot blow the recursion limit.
    """
    disc: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    counter = 0
    for root in adjacency:
        if root in disc:
            continue
        disc[root] = low[root] = counter
        parent[root] = None
        counter += 1
        stack: list[tuple[str, Iterator[tuple[str, float]]]] = [(root, iter(adjacency[root]))]
        while stack:
            node, neighbors = stack[-1]
            descended = False
            for neighbor, _weight in neighbors:
                if neighbor == parent[node]:
                    continue
                if neighbor in disc:
                    if disc[neighbor] < disc[node]:
                        low[node] = min(low[node], disc[neighbor])
                        on_edge(node, neighbor)
                    continue
                disc[neighbor] = low[neighbor] = counter
                parent[neighbor] = node
                counter += 1
                on_edge(node, neighbor)
                stack.append((neighbor, iter(adjacency[neighbor])))
                descended = True
                break
            if descended:
                continue
            stack.pop()
            up = parent[node]
            if up is not None:
                low[up] = min(low[up], low[node])
                on_finish(node, up, low[node], disc[up])

def bridge_edges(adjacency: dict[str, list[tuple[str, float]]]) -> set[tuple[str, str]]:
    """Every bridge span of a weighted graph, found in one linear DFS.

    An edge ``(u, v)`` is a bridge when the subtree rooted at ``v`` has no back edge
    reaching ``u`` or above (``low[v] > disc[u]``). Suited to the full carrier graph, where
    the edge-probing :func:`bridges` would be far too slow.
    """
    found: set[tuple[str, str]] = set()

    def record(node: str, up: str, low_node: int, disc_up: int) -> None:
        if low_node > disc_up:
            found.add(edge_key(up, node))

    _lowlink_dfs(adjacency, lambda _u, _v: None, record)
    return found

def two_edge_components(adjacency: dict[str, list[tuple[str, float]]]) -> dict[str, int]:
    """Label each vertex with its 2-edge-connected component id.

    Two vertices share a component exactly when no single span separates them -- so a
    set of backbone nodes can be wired into a fiber-resilient (bridgeless) mesh iff they
    all carry the same label. Computed once over the carrier graph and reused as the
    search's cheap feasibility oracle. Deleting the bridges leaves the components as the
    connected pieces; a vertex whose every span is a bridge is its own singleton.
    """
    cut = bridge_edges(adjacency)
    surviving = {
        edge_key(node, neighbor)
        for node, neighbors in adjacency.items()
        for neighbor, _weight in neighbors
        if edge_key(node, neighbor) not in cut
    }
    components = connected_components(set(adjacency), surviving)
    return {
        vertex_id: index
        for index, component in enumerate(components)
        for vertex_id in component
    }

def _record_block(
    edge_stack: list[tuple[str, str]],
    marker: tuple[str, str],
    blocks: list[set[str]],
) -> None:
    """Pop one biconnected component off the edge stack down to ``marker``.

    Records the popped vertices as a new block only when it is non-trivial (more than one
    span); a single-span pop is a bridge and earns no block.
    """
    block = [edge_stack.pop()]
    while block[-1] != marker:
        block.append(edge_stack.pop())
    if len(block) >= 2:
        blocks.append({vertex for span in block for vertex in span})

def biconnected_block_membership(
    adjacency: dict[str, list[tuple[str, float]]],
) -> dict[str, frozenset[int]]:
    """Label each vertex with the non-trivial biconnected blocks it belongs to.

    A block is a maximal 2-vertex-connected piece -- a set of vertices on a common cycle.
    Blocks overlap: a cut vertex belongs to several, so each vertex carries a *set* of
    block ids (unlike :func:`two_edge_components`, whose 2-edge-connected components form a
    clean partition). A set of backbone nodes can be wired into a city-survivable
    (no single-vertex cut) physical mesh iff they all share one common block, so the gate
    is a non-empty intersection of their block sets.

    Bridge spans are conventionally their own block, but two cities joined only by a bridge
    are not on a common cycle and are not even cable-survivable; such trivial (single-edge)
    blocks get **no id**, so a city all of whose spans are bridges maps to the empty set and
    fails the gate. A Hopcroft--Tarjan pass over an explicit edge stack, driven by the shared
    iterative low-link DFS (:func:`_lowlink_dfs`): each span is pushed as it is walked, and a
    finished node whose subtree cannot climb above its parent closes off one block.
    """
    edge_stack: list[tuple[str, str]] = []
    blocks: list[set[str]] = []

    def push(node: str, neighbor: str) -> None:
        edge_stack.append(edge_key(node, neighbor))

    def close(node: str, up: str, low_node: int, disc_up: int) -> None:
        if low_node >= disc_up:
            _record_block(edge_stack, edge_key(up, node), blocks)

    _lowlink_dfs(adjacency, push, close)
    return {
        node: frozenset(index for index, block in enumerate(blocks) if node in block)
        for node in adjacency
    }

def is_two_edge_connected(vertex_ids: set[str], edges: set[tuple[str, str]]) -> bool:
    """True if the graph is connected and survives the loss of any single edge.

    A graph is 2-edge-connected when it is connected and bridgeless.
    """
    if len(connected_components(vertex_ids, edges)) != 1:
        return False
    return not bridges(vertex_ids, edges)

def is_two_vertex_connected(vertex_ids: set[str], edges: set[tuple[str, str]]) -> bool:
    """True if the graph is connected and survives the loss of any single vertex.

    A graph is 2-vertex-connected (biconnected) when it is connected and has no
    articulation point -- the city-loss analogue of :func:`is_two_edge_connected`.
    """
    if len(connected_components(vertex_ids, edges)) != 1:
        return False
    return not articulation_points(vertex_ids, edges)

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
