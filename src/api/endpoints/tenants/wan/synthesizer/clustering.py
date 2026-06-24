"""Scale-adaptive clustering of access vertices into intentional aggregation clusters.

Aggregation points are placed as the heads of genuine clusters -- groups of at
least ``MIN_POINTS`` access vertices that hang together geographically -- so a new
accredited facility is built only where it aggregates real demand. Membership is
decided *relatively*, by a mutual k-nearest-neighbor graph: two access vertices
are linked only when each is among the other's ``k`` nearest, and clusters are the
connected components of that graph. This adapts to local density -- a dense metro
links at a few miles, a spread-out regional group (the Kansas City bases, ~85-105
mi apart) links at its own wider scale -- so no single global radius has to be
right everywhere at once. ``MAX_RADIUS_MILES`` survives only as a sanity guard
that keeps a link from ever bridging unrelated regions across the continent.
"""

from __future__ import annotations

from synthesizer.input_graph import Vertex, haversine_miles

# Default algorithm dials, mirrored by the matching ``DesignParams`` fields so a
# direct caller (and the test suite) need not pass them; ``etc/*.yml`` drives the
# real run. A cluster needs at least this many access vertices (``MIN_POINTS``).
# ``k`` (the mutual-neighbor count) defaults to ``MIN_POINTS``: raise it to pull
# second-ring outliers into a cluster, lower it for tighter groups. ``MIN_RADIUS``
# is only the fallback returned when there is nothing to cluster; ``MAX_RADIUS`` is
# the continent-bridge guard -- a link longer than this is never formed, no matter
# how mutual, so far-flung regions cannot fuse into one cluster.
MIN_POINTS = 2
MIN_RADIUS_MILES = 50.0
MAX_RADIUS_MILES = 250.0


def pairwise_miles(vertices: list[Vertex]) -> list[list[float]]:
    """Full symmetric matrix of great-circle distances between access vertices."""
    count = len(vertices)
    matrix = [[0.0] * count for _ in range(count)]
    for i in range(count):
        for j in range(i + 1, count):
            distance = haversine_miles(vertices[i], vertices[j])
            matrix[i][j] = matrix[j][i] = distance
    return matrix


def _nearest_indices(row: list[float], k: int) -> set[int]:
    """The indices of the ``k`` nearest other points (positive distance, ties by index)."""
    others = sorted(
        (distance, index) for index, distance in enumerate(row) if distance > 0.0
    )
    return {index for _distance, index in others[:k]}


def mutual_knn_neighbors(
    matrix: list[list[float]], k: int, max_radius: float
) -> list[set[int]]:
    """Undirected adjacency of the mutual k-nearest-neighbor graph.

    ``j`` is a neighbor of ``i`` only when each is among the other's ``k`` nearest
    *and* the two sit within ``max_radius`` of each other -- the guard that keeps a
    mutual pair from bridging unrelated regions across the continent.
    """
    count = len(matrix)
    nearest = [_nearest_indices(matrix[i], k) for i in range(count)]
    neighbors: list[set[int]] = [set() for _ in range(count)]
    for i in range(count):
        for j in nearest[i]:
            if i in nearest[j] and matrix[i][j] <= max_radius:
                neighbors[i].add(j)
                neighbors[j].add(i)
    return neighbors


def connected_components(neighbors: list[set[int]]) -> list[list[int]]:
    """Connected components of an undirected graph, each sorted, ordered by least index."""
    seen = [False] * len(neighbors)
    components: list[list[int]] = []
    for start in range(len(neighbors)):
        if seen[start]:
            continue
        component: list[int] = []
        stack = [start]
        seen[start] = True
        while stack:
            node = stack.pop()
            component.append(node)
            for other in neighbors[node]:
                if not seen[other]:
                    seen[other] = True
                    stack.append(other)
        components.append(sorted(component))
    return components


def cluster_access_vertices(
    access_vertices: list[Vertex],
    min_points: int = MIN_POINTS,
    min_radius: float = MIN_RADIUS_MILES,
    max_radius: float = MAX_RADIUS_MILES,
    k: int | None = None,
) -> tuple[list[list[str]], list[str], float]:
    """Group access vertices into clusters, returning (clusters, sparse_ids, radius).

    ``clusters`` is a list of access-vertex id lists (each a connected component of
    the mutual k-NN graph with at least ``min_points`` members, worth its own
    aggregation heads); ``sparse_ids`` are vertices in no such component and must
    reuse an existing facility; ``radius`` is a representative neighborhood distance
    (the widest link inside any cluster, clamped to the band) kept for the contract
    and diagnostics. ``k`` defaults to ``min_points``.
    """
    count = len(access_vertices)
    if count < min_points:
        return [], [vertex.id for vertex in access_vertices], min_radius
    k = min(k if k is not None else min_points, count - 1)
    matrix = pairwise_miles(access_vertices)
    neighbors = mutual_knn_neighbors(matrix, k, max_radius)
    clusters: list[list[str]] = []
    sparse: list[str] = []
    clustered: list[int] = []
    for component in connected_components(neighbors):
        if len(component) >= min_points:
            clusters.append([access_vertices[i].id for i in component])
            clustered.extend(component)
        else:
            sparse.extend(access_vertices[i].id for i in component)
    widest = max(
        (matrix[i][j] for i in clustered for j in neighbors[i]), default=min_radius
    )
    radius = max(min_radius, min(max_radius, widest))
    return clusters, sparse, radius
