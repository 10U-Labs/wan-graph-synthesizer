from __future__ import annotations

import heapq
import math
from collections import deque
from collections.abc import Callable, Iterator

from synthesizer.input_graph import FiberSegment, link_key


def dijkstra(
    adjacency: dict[str, list[tuple[str, float]]],
    source: str,
    blocked: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[dict[str, float], dict[str, str]]:
    distances = {source: 0.0}
    predecessors: dict[str, str] = {}
    queue = [(0.0, source)]

    while queue:
        distance, site_id = heapq.heappop(queue)
        if distance > distances[site_id] + 1e-9:
            continue
        for neighbor, weight in adjacency.get(site_id, []):
            if blocked and link_key(site_id, neighbor) in blocked:
                continue
            new_distance = distance + weight
            if new_distance + 1e-9 < distances.get(neighbor, math.inf):
                distances[neighbor] = new_distance
                predecessors[neighbor] = site_id
                heapq.heappush(queue, (new_distance, neighbor))

    return distances, predecessors

def reconstruct_path(source: str, target: str, predecessors: dict[str, str]) -> tuple[str, ...]:
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

def path_link_keys(path: tuple[str, ...]) -> set[tuple[str, str]]:
    return {link_key(path[index], path[index + 1]) for index in range(len(path) - 1)}

def undirected_adjacency(
    site_ids: set[str], links: set[tuple[str, str]]
) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {site_id: set() for site_id in site_ids}
    for left, right in links:
        if left in adjacency and right in adjacency:
            adjacency[left].add(right)
            adjacency[right].add(left)
    return adjacency

def connected_components(site_ids: set[str], links: set[tuple[str, str]]) -> list[list[str]]:
    adjacency = undirected_adjacency(site_ids, links)
    remaining = set(adjacency)
    components: list[list[str]] = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        queue: deque[str] = deque([start])
        component: list[str] = []
        while queue:
            site_id = queue.popleft()
            component.append(site_id)
            for neighbor in sorted(adjacency[site_id]):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
        components.append(sorted(component))
    return components

def reachable_over(
    adjacency: dict[str, list[tuple[str, float]]],
) -> dict[str, frozenset[str]]:
    segments = {
        link_key(city, neighbor)
        for city, neighbors in adjacency.items()
        for neighbor, _weight in neighbors
    }
    return {
        city: frozenset(group)
        for group in connected_components(set(adjacency), segments)
        for city in group
    }

def bridges(site_ids: set[str], links: set[tuple[str, str]]) -> set[tuple[str, str]]:
    base = len(connected_components(site_ids, links))
    return {
        link
        for link in links
        if len(connected_components(site_ids, links - {link})) > base
    }

def _lowlink_dfs(
    adjacency: dict[str, list[tuple[str, float]]],
    on_link: Callable[[str, str], None],
    on_finish: Callable[[str, str, int, int], None],
) -> None:
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
                        on_link(node, neighbor)
                    continue
                disc[neighbor] = low[neighbor] = counter
                parent[neighbor] = node
                counter += 1
                on_link(node, neighbor)
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

def bridge_links(adjacency: dict[str, list[tuple[str, float]]]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()

    def record(node: str, up: str, low_node: int, disc_up: int) -> None:
        if low_node > disc_up:
            found.add(link_key(up, node))

    _lowlink_dfs(adjacency, lambda _u, _v: None, record)
    return found

def bridgeless_components(adjacency: dict[str, list[tuple[str, float]]]) -> dict[str, int]:
    cut = bridge_links(adjacency)
    surviving = {
        link_key(node, neighbor)
        for node, neighbors in adjacency.items()
        for neighbor, _weight in neighbors
        if link_key(node, neighbor) not in cut
    }
    components = connected_components(set(adjacency), surviving)
    return {
        site_id: index
        for index, component in enumerate(components)
        for site_id in component
    }

def _record_block(
    link_stack: list[tuple[str, str]],
    marker: tuple[str, str],
    blocks: list[set[str]],
) -> None:
    block = [link_stack.pop()]
    while block[-1] != marker:
        block.append(link_stack.pop())
    if len(block) >= 2:
        blocks.append({site for segment in block for site in segment})

def biconnected_block_membership(
    adjacency: dict[str, list[tuple[str, float]]],
) -> dict[str, frozenset[int]]:
    link_stack: list[tuple[str, str]] = []
    blocks: list[set[str]] = []

    def push(node: str, neighbor: str) -> None:
        link_stack.append(link_key(node, neighbor))

    def close(node: str, up: str, low_node: int, disc_up: int) -> None:
        if low_node >= disc_up:
            _record_block(link_stack, link_key(up, node), blocks)

    _lowlink_dfs(adjacency, push, close)
    return {
        node: frozenset(index for index, block in enumerate(blocks) if node in block)
        for node in adjacency
    }

def survives_any_one_link_loss(site_ids: set[str], links: set[tuple[str, str]]) -> bool:
    if len(connected_components(site_ids, links)) != 1:
        return False
    return not bridges(site_ids, links)

def survives_any_one_site_loss(site_ids: set[str], links: set[tuple[str, str]]) -> bool:
    if len(connected_components(site_ids, links)) != 1:
        return False
    return not articulation_points(site_ids, links)

def articulation_points(site_ids: set[str], links: set[tuple[str, str]]) -> set[str]:
    adjacency = undirected_adjacency(site_ids, links)
    visited: set[str] = set()
    discovery: dict[str, int] = {}
    low: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    points: set[str] = set()
    time = 0

    def dfs(site_id: str) -> None:
        nonlocal time
        visited.add(site_id)
        discovery[site_id] = time
        low[site_id] = time
        time += 1
        children = 0

        for neighbor in sorted(adjacency[site_id]):
            if neighbor not in visited:
                parent[neighbor] = site_id
                children += 1
                dfs(neighbor)
                low[site_id] = min(low[site_id], low[neighbor])
                if parent.get(site_id) is None and children > 1:
                    points.add(site_id)
                if parent.get(site_id) is not None and low[neighbor] >= discovery[site_id]:
                    points.add(site_id)
            elif neighbor != parent.get(site_id):
                low[site_id] = min(low[site_id], discovery[neighbor])

    for site_id in sorted(adjacency):
        if site_id not in visited:
            parent[site_id] = None
            dfs(site_id)

    return points


def build_adjacency(
    links: dict[tuple[str, str], FiberSegment],
) -> dict[str, list[tuple[str, float]]]:
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for (left, right), link in links.items():
        adjacency.setdefault(left, []).append((right, link.distance_miles))
        adjacency.setdefault(right, []).append((left, link.distance_miles))
    for neighbors in adjacency.values():
        neighbors.sort()
    return adjacency


def adjacency_by_carrier(
    links: dict[tuple[str, str], FiberSegment],
) -> dict[str, dict[str, list[tuple[str, float]]]]:
    carriers = sorted({carrier for link in links.values() for carrier in link.carriers})
    return {
        carrier: build_adjacency({
            key: link
            for key, link in links.items()
            if not link.carriers or carrier in link.carriers
        })
        for carrier in carriers
    }
