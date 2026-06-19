"""Unit tests for scale-adaptive (mutual k-NN) clustering of access vertices."""

from __future__ import annotations

import fixtures
from wan_designer.clustering import (
    MAX_RADIUS_MILES,
    MIN_RADIUS_MILES,
    cluster_access_vertices,
    connected_components,
    mutual_knn_neighbors,
    pairwise_miles,
)

access = fixtures.access_vertex

# The real Kansas City / Missouri / Kansas regional cluster of access vertices,
# spaced ~85-105 mi apart -- the spread-out group a single global DBSCAN radius
# (capped at 70 mi) marked as noise. Offutt AFB (Omaha, ~130 mi north) is left
# out: at the default k=2 cohesion it stays its own node, not part of KC.
KC_REGION = [
    access("Fort Leavenworth", 39.3556, -94.9152),
    access("Whiteman AFB", 38.7300, -93.5480),
    access("Fort Riley", 39.0858, -96.8047),
    access("Fort Leonard Wood", 37.7531, -92.1296),
    access("McConnell AFB", 37.6210, -97.2670),
]


def line_matrix(positions: list[float]) -> list[list[float]]:
    """A distance matrix for points on a line: entry (i, j) is |posi - posj|."""
    return [[abs(left - right) for right in positions] for left in positions]


def test_pairwise_miles_is_symmetric() -> None:
    """The distance matrix is symmetric across the diagonal."""
    matrix = pairwise_miles([access("a", 0.0, 0.0), access("b", 1.0, 2.0)])
    assert matrix[0][1] == matrix[1][0]


def test_mutual_knn_excludes_a_one_directional_neighbor() -> None:
    """A point in another's k-nearest but not vice-versa is not connected.

    On the line 0,1,2,100: 100's nearest is 2, but 2's nearest are 0 and 1, so
    the edge is one-directional and dropped -- 100 has no mutual neighbor.
    """
    neighbors = mutual_knn_neighbors(line_matrix([0.0, 1.0, 2.0, 100.0]), k=2, max_radius=1000.0)
    assert neighbors[3] == set()


def test_mutual_knn_respects_the_max_radius_guard() -> None:
    """A mutual pair farther apart than max_radius is not connected."""
    neighbors = mutual_knn_neighbors(line_matrix([0.0, 100.0]), k=1, max_radius=50.0)
    assert neighbors[0] == set()


def test_connected_components_groups_a_chain() -> None:
    """A chain 0-1-2 (each linked to its successor) is one component."""
    components = connected_components([{1}, {0, 2}, {1}])
    assert components == [[0, 1, 2]]


def test_cluster_access_vertices_returns_no_clusters_when_too_few() -> None:
    """Fewer than the minimum points yields no clusters at all."""
    clusters, _sparse, _radius = cluster_access_vertices([access("a")])
    assert clusters == []


def test_cluster_access_vertices_groups_a_dense_metro() -> None:
    """Four tightly co-located access vertices form a single cluster."""
    vertices = [access(name, 40.0, -100.0 + offset) for name, offset in
             (("a", 0.0), ("b", 0.05), ("c", 0.1), ("d", 0.15))]
    clusters, _sparse, _radius = cluster_access_vertices(vertices)
    assert len(clusters) == 1


def test_cluster_access_vertices_leaves_a_far_vertex_sparse() -> None:
    """A vertex far from a dense metro is left sparse, not forced into the cluster."""
    vertices = [access("a", 40.0, -100.0), access("b", 40.0, -100.05),
             access("c", 40.0, -100.1), access("far", 25.0, -80.0)]
    _clusters, sparse, _radius = cluster_access_vertices(vertices)
    assert sparse == ["far"]


def test_cluster_access_vertices_groups_the_spread_out_kc_region() -> None:
    """The spread-out KC bases (~85-105 mi apart) form a single cluster."""
    clusters, _sparse, _radius = cluster_access_vertices(KC_REGION, max_radius=150.0)
    assert len(clusters) == 1


def test_cluster_access_vertices_leaves_no_kc_base_sparse() -> None:
    """Every KC base joins the cluster -- none is dropped as noise."""
    _clusters, sparse, _radius = cluster_access_vertices(KC_REGION, max_radius=150.0)
    assert sparse == []


def test_cluster_access_vertices_keeps_distant_metros_separate() -> None:
    """Two tight metros ~200 mi apart stay two clusters, never merging."""
    east = [access(f"e{i}", 40.0, -96.0 + 0.05 * i) for i in range(3)]
    west = [access(f"w{i}", 40.0, -100.0 + 0.05 * i) for i in range(3)]
    clusters, _sparse, _radius = cluster_access_vertices(east + west)
    assert len(clusters) == 2


def test_cluster_access_vertices_guard_blocks_a_continental_bridge() -> None:
    """Two lone points farther apart than max_radius stay sparse, never bridged."""
    vertices = [access("east", 40.0, -74.0), access("west", 37.0, -122.0)]
    clusters, _sparse, _radius = cluster_access_vertices(vertices, max_radius=MAX_RADIUS_MILES)
    assert clusters == []


def test_cluster_access_vertices_filters_a_pair_below_min_points() -> None:
    """A lone mutual pair is dropped when min_points exceeds the pair size."""
    vertices = [access("a", 40.0, -100.0), access("b", 40.0, -100.3)]
    clusters, _sparse, _radius = cluster_access_vertices(vertices, min_points=3)
    assert clusters == []


def test_cluster_access_vertices_keeps_a_pair_at_min_points_two() -> None:
    """That same lone mutual pair is a cluster at the default min_points=2."""
    vertices = [access("a", 40.0, -100.0), access("b", 40.0, -100.3)]
    clusters, _sparse, _radius = cluster_access_vertices(vertices, min_points=2)
    assert len(clusters) == 1


def test_cluster_access_vertices_radius_stays_within_band() -> None:
    """The returned representative radius is clamped into the configured band."""
    clusters_radius = cluster_access_vertices(KC_REGION, max_radius=150.0)[2]
    assert MIN_RADIUS_MILES <= clusters_radius <= 150.0
