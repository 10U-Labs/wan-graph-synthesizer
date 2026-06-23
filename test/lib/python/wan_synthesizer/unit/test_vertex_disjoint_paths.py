"""Unit tests for vertex-disjoint aggregation-to-core routing.

These tests pin down the core resilience fix: an aggregation must reach two
distinct core vertices over two vertex-disjoint paths, otherwise a single vertex or
link failure severs it from the core tier.
"""

from __future__ import annotations

import math

from wan_synthesizer.graphs import vertex_disjoint_paths_to_cores


def adjacency_from_edges(
    edges: list[tuple[str, str, float]],
) -> dict[str, list[tuple[str, float]]]:
    """Build an undirected weighted adjacency map from (u, v, distance) edges."""
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for left, right, distance in edges:
        adjacency.setdefault(left, []).append((right, distance))
        adjacency.setdefault(right, []).append((left, distance))
    for neighbors in adjacency.values():
        neighbors.sort()
    return adjacency


DIAMOND = adjacency_from_edges(
    [
        ("S", "A", 1.0),
        ("S", "B", 1.0),
        ("A", "C1", 1.0),
        ("B", "C2", 1.0),
    ]
)

# A single cut vertex X sits between the source and both cores: no two
# vertex-disjoint paths to two cores can exist (the Reno/Goodyear pattern).
BOTTLENECK = adjacency_from_edges(
    [
        ("S", "X", 1.0),
        ("X", "C1", 1.0),
        ("X", "C2", 1.0),
    ]
)

# Source with only one physical link can never be dual-homed.
STUB = adjacency_from_edges(
    [
        ("S", "A", 1.0),
        ("A", "C1", 1.0),
        ("A", "C2", 1.0),
    ]
)


def test_diamond_returns_two_paths() -> None:
    """Diamond returns two paths."""
    _distance, paths = vertex_disjoint_paths_to_cores(DIAMOND, "S", ("C1", "C2"))
    assert len(paths) == 2


def test_diamond_reaches_two_distinct_cores() -> None:
    """Diamond reaches two distinct cores."""
    _distance, paths = vertex_disjoint_paths_to_cores(DIAMOND, "S", ("C1", "C2"))
    assert {path[-1] for path in paths} == {"C1", "C2"}


def test_diamond_paths_share_only_the_source() -> None:
    """Diamond paths share only the source."""
    _distance, paths = vertex_disjoint_paths_to_cores(DIAMOND, "S", ("C1", "C2"))
    shared = set(paths[0][1:]) & set(paths[1][1:])
    assert shared == set()


def test_diamond_reports_total_distance() -> None:
    """Diamond reports total distance."""
    distance, _paths = vertex_disjoint_paths_to_cores(DIAMOND, "S", ("C1", "C2"))
    assert distance == 4.0


def test_diamond_paths_start_at_source() -> None:
    """Diamond paths start at source."""
    _distance, paths = vertex_disjoint_paths_to_cores(DIAMOND, "S", ("C1", "C2"))
    assert all(path[0] == "S" for path in paths)


def test_bottleneck_is_infeasible_no_paths() -> None:
    """Bottleneck is infeasible no paths."""
    _distance, paths = vertex_disjoint_paths_to_cores(BOTTLENECK, "S", ("C1", "C2"))
    assert not paths


def test_bottleneck_is_infeasible_infinite_distance() -> None:
    """Bottleneck is infeasible infinite distance."""
    distance, _paths = vertex_disjoint_paths_to_cores(BOTTLENECK, "S", ("C1", "C2"))
    assert distance == math.inf


def test_degree_one_source_is_infeasible() -> None:
    """Degree one source is infeasible."""
    _distance, paths = vertex_disjoint_paths_to_cores(STUB, "S", ("C1", "C2"))
    assert not paths


def test_three_cores_still_returns_two_paths() -> None:
    """Three cores still returns two paths."""
    adjacency = adjacency_from_edges(
        [
            ("S", "A", 1.0),
            ("S", "B", 1.0),
            ("A", "C1", 1.0),
            ("B", "C2", 1.0),
            ("B", "C3", 5.0),
        ]
    )
    _distance, paths = vertex_disjoint_paths_to_cores(adjacency, "S", ("C1", "C2", "C3"))
    assert len(paths) == 2


def test_dense_graph_routes_two_disjoint_paths() -> None:
    """Dense graph routes two disjoint paths."""
    adjacency = adjacency_from_edges(
        [
            ("S", "A", 1.0),
            ("S", "B", 1.0),
            ("A", "B", 1.0),
            ("A", "C1", 1.0),
            ("A", "C2", 3.0),
            ("B", "C1", 3.0),
            ("B", "C2", 1.0),
        ]
    )
    _distance, paths = vertex_disjoint_paths_to_cores(adjacency, "S", ("C1", "C2"))
    assert {path[-1] for path in paths} == {"C1", "C2"}


def test_fewer_cores_than_count_is_infeasible() -> None:
    """Fewer cores than count is infeasible."""
    _distance, paths = vertex_disjoint_paths_to_cores(DIAMOND, "S", ("C1",), 2)
    assert not paths


def test_source_absent_from_graph_is_infeasible() -> None:
    """Source absent from graph is infeasible."""
    _distance, paths = vertex_disjoint_paths_to_cores(DIAMOND, "Z", ("C1", "C2"))
    assert not paths


def test_prefers_cheaper_pair_of_cores() -> None:
    """Prefers cheaper pair of cores."""
    adjacency = adjacency_from_edges(
        [
            ("S", "A", 1.0),
            ("S", "B", 1.0),
            ("A", "C1", 1.0),
            ("B", "C2", 1.0),
            ("B", "C3", 50.0),
        ]
    )
    _distance, paths = vertex_disjoint_paths_to_cores(adjacency, "S", ("C1", "C2", "C3"))
    assert {path[-1] for path in paths} == {"C1", "C2"}


# Default routing prefers the cheap C1+C2 pair; forcing the far C3 must override it.
FORCED_CORE_GRAPH = adjacency_from_edges(
    [
        ("S", "A", 1.0),
        ("S", "B", 1.0),
        ("A", "C1", 1.0),
        ("B", "C2", 1.0),
        ("A", "C3", 10.0),
    ]
)


def test_required_core_is_one_of_the_path_endpoints() -> None:
    """A required core is forced to terminate one of the disjoint paths."""
    _distance, paths = vertex_disjoint_paths_to_cores(
        FORCED_CORE_GRAPH, "S", ("C1", "C2", "C3"), 2, frozenset({"C3"})
    )
    assert "C3" in {path[-1] for path in paths}


def test_required_core_still_returns_two_distinct_cores() -> None:
    """Forcing one core still yields two vertex-disjoint paths to two distinct cores."""
    _distance, paths = vertex_disjoint_paths_to_cores(
        FORCED_CORE_GRAPH, "S", ("C1", "C2", "C3"), 2, frozenset({"C3"})
    )
    assert {path[-1] for path in paths} == {"C2", "C3"}


def test_two_required_cores_behind_one_cut_is_infeasible() -> None:
    """Two required cores that share a single exit cannot both anchor disjoint paths.

    C2 and C3 both sit behind B (C3 hangs off C2), so a path to each would reuse B
    -- they cannot be vertex-disjoint, even though the graph has two disjoint paths
    to other cores. Forcing both is infeasible.
    """
    adjacency = adjacency_from_edges(
        [("S", "A", 1.0), ("S", "B", 1.0), ("A", "C1", 1.0), ("B", "C2", 1.0), ("C2", "C3", 1.0)]
    )
    _distance, paths = vertex_disjoint_paths_to_cores(
        adjacency, "S", ("C1", "C2", "C3"), 2, frozenset({"C2", "C3"})
    )
    assert not paths


def test_required_core_absent_from_core_set_is_infeasible() -> None:
    """A required core that is not among the candidate cores is infeasible."""
    _distance, paths = vertex_disjoint_paths_to_cores(
        DIAMOND, "S", ("C1", "C2"), 2, frozenset({"C9"})
    )
    assert not paths
