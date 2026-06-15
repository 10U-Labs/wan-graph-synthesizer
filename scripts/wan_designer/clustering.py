"""Density clustering (DBSCAN) of access vertices into intentional aggregation clusters.

Aggregation points are placed as the heads of genuine clusters -- groups of at
least ``MIN_POINTS`` access vertices that sit close together -- so a new accredited
facility is built only where it aggregates many geographically close access
vertices. The neighborhood radius is derived from the data (the elbow of the sorted
k-nearest-neighbor distances), not a hand-picked constant, then clamped to a
sane metro-to-regional band so far-flung outliers cannot merge unrelated metros
or shatter real ones.
"""

from __future__ import annotations

from wan_designer.model import Vertex, haversine_miles

# Default algorithm dials, mirrored by the matching ``DesignParams`` fields so a
# direct caller (and the test suite) need not pass them; ``etc/config.yml`` drives
# the real run. A cluster needs at least this many close access vertices (DBSCAN
# minPts, N). The radius is clamped to a metro-to-regional band: the floor keeps a
# single dense metro from fragmenting; the ceiling keeps a distant PoP (e.g. Boise,
# ~276 mi from the Utah sites) from ever counting as that cluster's local head.
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


def knee_value(sorted_values: list[float], fallback: float = MIN_RADIUS_MILES) -> float:
    """The value at the elbow of an ascending curve (max distance from its chord).

    Standard kneedle-style detection: the point of the sorted k-distance curve
    that sits farthest from the straight line joining its first and last points
    marks where distances start climbing steeply -- the density boundary.
    """
    count = len(sorted_values)
    if count < 3:
        return sorted_values[-1] if sorted_values else fallback
    first, last = sorted_values[0], sorted_values[-1]
    span = last - first
    if span <= 0.0:
        return first
    best_index, best_gap = 0, -1.0
    for index, value in enumerate(sorted_values):
        # Vertical gap between the chord and the curve at this index.
        chord = first + span * (index / (count - 1))
        gap = chord - value
        if gap > best_gap:
            best_gap, best_index = gap, index
    return sorted_values[best_index]


def derive_radius(
    matrix: list[list[float]],
    min_points: int = MIN_POINTS,
    min_radius: float = MIN_RADIUS_MILES,
    max_radius: float = MAX_RADIUS_MILES,
) -> float:
    """Derive the DBSCAN radius from the k-distance elbow (k = ``min_points``)."""
    count = len(matrix)
    if count <= min_points:
        return min_radius
    k_distances: list[float] = []
    for row in matrix:
        others = sorted(distance for distance in row if distance > 0.0)
        if len(others) >= min_points:
            k_distances.append(others[min_points - 1])
    if not k_distances:
        return min_radius
    k_distances.sort()
    radius = knee_value(k_distances, min_radius)
    return max(min_radius, min(max_radius, radius))


def dbscan_labels(
    matrix: list[list[float]], radius: float, min_points: int = MIN_POINTS
) -> list[int]:
    """Label each vertex with its cluster id, or -1 for noise (a sparse, lone vertex).

    Standard DBSCAN: a vertex is a core point when at least ``min_points`` vertices
    (itself included) lie within ``radius``; clusters grow by absorbing the
    neighborhoods of core points. Border points join a touching cluster; vertices
    in neither are noise.
    """
    count = len(matrix)
    neighbors = [
        [j for j in range(count) if matrix[i][j] <= radius] for i in range(count)
    ]
    labels = [-1] * count
    cluster = -1
    for point in range(count):
        if labels[point] != -1 or len(neighbors[point]) < min_points:
            continue  # already assigned, or not a core point (left as noise)
        cluster += 1
        labels[point] = cluster
        queue = [other for other in neighbors[point] if other != point]
        while queue:
            other = queue.pop()
            if labels[other] != -1:
                continue  # already absorbed by this or an earlier cluster
            labels[other] = cluster
            if len(neighbors[other]) >= min_points:  # a core point: grow outward
                queue.extend(near for near in neighbors[other] if labels[near] == -1)
    return labels


def cluster_access_vertices(
    access_vertices: list[Vertex],
    min_points: int = MIN_POINTS,
    min_radius: float = MIN_RADIUS_MILES,
    max_radius: float = MAX_RADIUS_MILES,
) -> tuple[list[list[str]], list[str], float]:
    """Group access vertices into clusters, returning (clusters, sparse_ids, radius).

    ``clusters`` is a list of access-vertex id lists (each a dense group worth its
    own aggregation heads); ``sparse_ids`` are lone vertices that belong to no
    cluster and must reuse an existing facility; ``radius`` is the derived
    neighborhood distance, reused downstream to decide which PoPs are local
    enough to be a cluster's head.
    """
    if len(access_vertices) < min_points:
        return [], [vertex.id for vertex in access_vertices], min_radius
    matrix = pairwise_miles(access_vertices)
    radius = derive_radius(matrix, min_points, min_radius, max_radius)
    labels = dbscan_labels(matrix, radius, min_points)
    clusters: dict[int, list[str]] = {}
    sparse: list[str] = []
    for vertex, label in zip(access_vertices, labels):
        if label == -1:
            sparse.append(vertex.id)
        else:
            clusters.setdefault(label, []).append(vertex.id)
    ordered = [clusters[key] for key in sorted(clusters)]
    return ordered, sparse, radius
