"""Unit tests for density clustering of access vertices."""

from __future__ import annotations

import pytest

import fixtures
from wan_designer.clustering import (
    MAX_RADIUS_MILES,
    MIN_RADIUS_MILES,
    cluster_access_vertices,
    dbscan_labels,
    derive_radius,
    knee_value,
    pairwise_miles,
)

access = fixtures.access_vertex


def line_matrix(positions: list[float]) -> list[list[float]]:
    """A distance matrix for points on a line: entry (i, j) is |posi - posj|."""
    return [[abs(left - right) for right in positions] for left in positions]


def test_pairwise_miles_is_symmetric() -> None:
    """The distance matrix is symmetric across the diagonal."""
    matrix = pairwise_miles([access("a", 0.0, 0.0), access("b", 1.0, 2.0)])
    assert matrix[0][1] == matrix[1][0]


@pytest.mark.parametrize(
    "values, expected",
    [
        ([], MIN_RADIUS_MILES),  # empty -> floor
        ([5.0], 5.0),  # single value -> itself
        ([3.0, 3.0, 3.0], 3.0),  # flat curve (no span) -> first
        ([1.0, 1.0, 1.0, 10.0], 1.0),  # elbow sits at the jump
    ],
)
def test_knee_value(values: list[float], expected: float) -> None:
    """The knee is the floor, the lone point, the flat value, or the elbow."""
    assert knee_value(values) == expected


@pytest.mark.parametrize(
    "matrix",
    [
        line_matrix([0.0, 1.0]),  # count <= min_points: too few to derive
        line_matrix([0.0, 0.0, 0.0, 0.0]),  # all coincident: no k-distances
    ],
)
def test_derive_radius_falls_back_to_floor(matrix: list[list[float]]) -> None:
    """Too few or fully coincident points fall back to the radius floor."""
    assert derive_radius(matrix) == MIN_RADIUS_MILES


@pytest.mark.parametrize(
    "matrix",
    [
        line_matrix([0.0, 1.0, 2.0, 3.0, 100.0]),  # a clear density boundary
        line_matrix([0.0, 0.0, 1.0, 2.0]),  # one coincident pair, rest distinct
    ],
)
def test_derive_radius_stays_within_band(matrix: list[list[float]]) -> None:
    """A derived radius is clamped into the metro-to-regional band."""
    assert MIN_RADIUS_MILES <= derive_radius(matrix) <= MAX_RADIUS_MILES


def test_dbscan_labels_marks_an_isolated_point_as_noise() -> None:
    """A point with too few neighbors is labeled noise (-1)."""
    labels = dbscan_labels(line_matrix([0.0, 1.0, 2.0, 100.0]), radius=5.0)
    assert labels[3] == -1


def test_dbscan_labels_groups_dense_points_together() -> None:
    """Points within the radius of a core point share its cluster."""
    labels = dbscan_labels(line_matrix([0.0, 1.0, 2.0, 100.0]), radius=5.0)
    assert labels[0] == labels[2]


def test_dbscan_labels_absorbs_a_border_point() -> None:
    """A non-core point within reach of a core joins that core's cluster."""
    labels = dbscan_labels(line_matrix([0.0, 1.0, 2.0, 4.0]), radius=2.5, min_points=3)
    assert labels[3] == labels[0]


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
