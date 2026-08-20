"""Graph algorithms: shortest paths and connectivity."""

from __future__ import annotations

import heapq
import math
from collections import deque
from collections.abc import Callable, Iterable, Iterator

from synthesizer.input_graph import FiberSegment, link_key


def distances_from(
    adjacency: dict[str, list[tuple[str, float]]],
    sources: Iterable[str],
) -> dict[str, dict[str, float]]:
    """Shortest-path distances to every city, from each of ``sources``.

    One Dijkstra per source. Enough for the backup path limit, which needs the distance
    from the site being measured and from each of its peers and nothing else, so the callers
    that already hold all-pairs distances pass those straight in rather than paying for
    this. A source the merged carriers do not carry gets a row holding only itself, which is
    what Dijkstra returns for it and reads correctly as reaching nothing.
    """
    return {source: dijkstra(adjacency, source)[0] for source in sources}


def dijkstra(
    adjacency: dict[str, list[tuple[str, float]]],
    source: str,
    blocked: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[dict[str, float], dict[str, str]]:
    """Shortest-path distances and predecessors from a single source.

    ``blocked`` is a set of ``link_key`` fiber segments the search may not traverse --
    used to draw a detour around a segment already carrying backbone traffic.
    """
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
    """Rebuild the site path from source to target via the predecessor map."""
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
    """Return the set of link keys traversed by a site path."""
    return {link_key(path[index], path[index + 1]) for index in range(len(path) - 1)}

def undirected_adjacency(
    site_ids: set[str], links: set[tuple[str, str]]
) -> dict[str, set[str]]:
    """Build an undirected neighbor map restricted to the given site ids."""
    adjacency: dict[str, set[str]] = {site_id: set() for site_id in site_ids}
    for left, right in links:
        if left in adjacency and right in adjacency:
            adjacency[left].add(right)
            adjacency[right].add(left)
    return adjacency

def connected_components(site_ids: set[str], links: set[tuple[str, str]]) -> list[list[str]]:
    """Return the connected components of the synthesis graph as sorted id lists."""
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

def bridges(site_ids: set[str], links: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """Return the links whose removal would raise the graph's component count.

    A bridge lies on no cycle, so deleting it splits its component in two. Site
    sets here are tiny (a handful of backbone nodes), so each link is probed by
    removal rather than via a linear-time bridge search.
    """
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
    """Iterative Tarjan low-link sweep, the shared skeleton of the connectivity passes.

    Calls ``on_link(u, v)`` for every tree link and every back link (to an ancestor), in
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
    """Every bridge segment of a weighted graph, found in one linear DFS.

    An link ``(u, v)`` is a bridge when the subtree rooted at ``v`` has no back link
    reaching ``u`` or above (``low[v] > disc[u]``). Suited to the full carrier graph, where
    the link-probing :func:`bridges` would be far too slow.
    """
    found: set[tuple[str, str]] = set()

    def record(node: str, up: str, low_node: int, disc_up: int) -> None:
        if low_node > disc_up:
            found.add(link_key(up, node))

    _lowlink_dfs(adjacency, lambda _u, _v: None, record)
    return found

def bridgeless_components(adjacency: dict[str, list[tuple[str, float]]]) -> dict[str, int]:
    """Label each site with its bridgeless component id.

    Two sites share a component exactly when no single segment separates them -- so a
    set of backbone nodes can be wired into a fiber-resilient (bridgeless) mesh iff they
    all carry the same label. Computed once over the carrier graph and reused as the
    search's cheap feasibility oracle. Deleting the bridges leaves the components as the
    connected pieces; a site whose every segment is a bridge is its own singleton.
    """
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
    """Pop one biconnected component off the link stack down to ``marker``.

    Records the popped sites as a new block only when it is non-trivial (more than one
    segment); a single-segment pop is a bridge and earns no block.
    """
    block = [link_stack.pop()]
    while block[-1] != marker:
        block.append(link_stack.pop())
    if len(block) >= 2:
        blocks.append({site for segment in block for site in segment})

def biconnected_block_membership(
    adjacency: dict[str, list[tuple[str, float]]],
) -> dict[str, frozenset[int]]:
    """Label each site with the non-trivial biconnected blocks it belongs to.

    A block is the largest piece no single site's loss can split -- a set of sites
    on a common cycle.
    Blocks overlap: a cut site belongs to several, so each site carries a *set* of
    block ids (unlike :func:`bridgeless_components`, whose bridgeless components form a
    clean partition). A set of backbone nodes can be wired into a city-survivable
    (no single-site cut) physical mesh iff they all share one common block, so the gate
    is a non-empty intersection of their block sets.

    Bridge segments are conventionally their own block, but two cities joined only by a
    bridge are not on a common cycle and do not even survive that one segment's loss; such
    trivial (single-link) blocks get **no id**, so a city all of whose segments are bridges
    maps to the empty set and
    fails the gate. A Hopcroft--Tarjan pass over an explicit link stack, driven by the shared
    iterative low-link DFS (:func:`_lowlink_dfs`): each segment is pushed as it is walked, and a
    finished node whose subtree cannot climb above its parent closes off one block.
    """
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
    """True if the graph is connected and survives the loss of any single link.

    A graph survives the loss of any one link when it is connected and bridgeless.
    """
    if len(connected_components(site_ids, links)) != 1:
        return False
    return not bridges(site_ids, links)

def survives_any_one_site_loss(site_ids: set[str], links: set[tuple[str, str]]) -> bool:
    """True if the graph is connected and survives the loss of any single site.

    A graph survives the loss of any one site when it is connected and has no
    articulation point -- the city-loss analogue of :func:`survives_any_one_link_loss`.
    """
    if len(connected_components(site_ids, links)) != 1:
        return False
    return not articulation_points(site_ids, links)

def articulation_points(site_ids: set[str], links: set[tuple[str, str]]) -> set[str]:
    """Return cut sites whose removal would disconnect the synthesis graph."""
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
    """Build a sorted weighted adjacency map from the physical links."""
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for (left, right), link in links.items():
        adjacency.setdefault(left, []).append((right, link.distance_miles))
        adjacency.setdefault(right, []).append((left, link.distance_miles))
    for neighbors in adjacency.values():
        neighbors.sort()
    return adjacency
