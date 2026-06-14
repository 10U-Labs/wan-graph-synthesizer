"""Density clustering (DBSCAN) of access nodes into intentional aggregation clusters.

Aggregation points are placed as the heads of genuine clusters -- groups of at
least ``MIN_POINTS`` access nodes that sit close together -- so a new accredited
facility is built only where it aggregates many geographically close access
nodes. The neighborhood radius is derived from the data (the elbow of the sorted
k-nearest-neighbor distances), not a hand-picked constant, then clamped to a
sane metro-to-regional band so far-flung outliers cannot merge unrelated metros
or shatter real ones.
"""

from __future__ import annotations

from wan_designer.model import Node, haversine_miles

# A cluster needs at least this many close access nodes (the DBSCAN minPts, N).
MIN_POINTS = 3

# Clamp the derived radius to a metro-to-regional band. The floor keeps a single
# dense metro from fragmenting; the ceiling keeps a distant PoP (e.g. Boise, ~276
# mi from the Utah sites) from ever counting as that cluster's local head.
MIN_RADIUS_MILES = 50.0
MAX_RADIUS_MILES = 250.0


def pairwise_miles(nodes: list[Node]) -> list[list[float]]:
    """Full symmetric matrix of great-circle distances between access nodes."""
    count = len(nodes)
    matrix = [[0.0] * count for _ in range(count)]
    for i in range(count):
        for j in range(i + 1, count):
            distance = haversine_miles(nodes[i], nodes[j])
            matrix[i][j] = matrix[j][i] = distance
    return matrix


def knee_value(sorted_values: list[float]) -> float:
    """The value at the elbow of an ascending curve (max distance from its chord).

    Standard kneedle-style detection: the point of the sorted k-distance curve
    that sits farthest from the straight line joining its first and last points
    marks where distances start climbing steeply -- the density boundary.
    """
    count = len(sorted_values)
    if count < 3:
        return sorted_values[-1] if sorted_values else MIN_RADIUS_MILES
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


def derive_radius(matrix: list[list[float]], min_points: int = MIN_POINTS) -> float:
    """Derive the DBSCAN radius from the k-distance elbow (k = ``min_points``)."""
    count = len(matrix)
    if count <= min_points:
        return MIN_RADIUS_MILES
    k_distances: list[float] = []
    for row in matrix:
        others = sorted(distance for distance in row if distance > 0.0)
        if len(others) >= min_points:
            k_distances.append(others[min_points - 1])
    if not k_distances:
        return MIN_RADIUS_MILES
    k_distances.sort()
    radius = knee_value(k_distances)
    return max(MIN_RADIUS_MILES, min(MAX_RADIUS_MILES, radius))


def dbscan_labels(
    matrix: list[list[float]], radius: float, min_points: int = MIN_POINTS
) -> list[int]:
    """Label each node with its cluster id, or -1 for noise (a sparse, lone node).

    Standard DBSCAN: a node is a core point when at least ``min_points`` nodes
    (itself included) lie within ``radius``; clusters grow by absorbing the
    neighborhoods of core points. Border points join a touching cluster; nodes
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


def cluster_access_nodes(
    access_nodes: list[Node], min_points: int = MIN_POINTS
) -> tuple[list[list[str]], list[str], float]:
    """Group access nodes into clusters, returning (clusters, sparse_ids, radius).

    ``clusters`` is a list of access-node id lists (each a dense group worth its
    own aggregation heads); ``sparse_ids`` are lone nodes that belong to no
    cluster and must reuse an existing facility; ``radius`` is the derived
    neighborhood distance, reused downstream to decide which PoPs are local
    enough to be a cluster's head.
    """
    if len(access_nodes) < min_points:
        return [], [node.id for node in access_nodes], MIN_RADIUS_MILES
    matrix = pairwise_miles(access_nodes)
    radius = derive_radius(matrix, min_points)
    labels = dbscan_labels(matrix, radius, min_points)
    clusters: dict[int, list[str]] = {}
    sparse: list[str] = []
    for node, label in zip(access_nodes, labels):
        if label == -1:
            sparse.append(node.id)
        else:
            clusters.setdefault(label, []).append(node.id)
    ordered = [clusters[key] for key in sorted(clusters)]
    return ordered, sparse, radius
