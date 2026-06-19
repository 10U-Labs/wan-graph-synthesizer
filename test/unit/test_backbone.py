"""Unit tests for core-backbone selection and routing."""

from __future__ import annotations

import fixtures
from wan_designer.model import (
    PathUse,
    edge_key,
)
from wan_designer.backbone import (
    BackboneConstraints,
    core_mesh_paths,
    select_core_backbone_pairs,
)
from wan_designer.optimize import all_pairs_shortest
from wan_designer.parsing import build_adjacency

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from


def test_core_mesh_paths_empty_when_cores_disconnected() -> None:
    """Core mesh paths empty when cores disconnected."""
    edges = physical({("a", "b"): 1.0, ("c", "d"): 1.0})
    adjacency = build_adjacency(edges)
    distances, predecessors = all_pairs_shortest(
        [pop("a"), pop("b"), pop("c"), pop("d")], adjacency
    )
    assert not core_mesh_paths(("a", "c"), distances, predecessors, edges)


def _symmetric_distances(weights: dict[tuple[str, str], float]) -> dict[str, dict[str, float]]:
    """Build a symmetric all-pairs distance table from undirected pair weights."""
    nodes = {node for pair in weights for node in pair}
    table: dict[str, dict[str, float]] = {node: {node: 0.0} for node in nodes}
    for (left, right), weight in weights.items():
        table[left][right] = weight
        table[right][left] = weight
    return table


# Five fully-connected cores with distinct finite inter-core distances.
_FIVE_CORE_DISTANCES = _symmetric_distances({
    ("c1", "c2"): 1.0, ("c1", "c3"): 2.0, ("c1", "c4"): 3.0, ("c1", "c5"): 10.0,
    ("c2", "c3"): 4.0, ("c2", "c4"): 5.0, ("c2", "c5"): 6.0,
    ("c3", "c4"): 7.0, ("c3", "c5"): 8.0,
    ("c4", "c5"): 9.0,
})
_FIVE_CORES = ("c1", "c2", "c3", "c4", "c5")


def _backbone(
    removed: frozenset[tuple[str, str]] = frozenset(), links_per_core: int = 3
) -> list[tuple[str, str]]:
    """The five-core backbone wiring each core to its nearest peers (asserted reachable)."""
    pairs = select_core_backbone_pairs(
        _FIVE_CORES, _FIVE_CORE_DISTANCES, removed, links_per_core
    )
    assert pairs is not None
    return pairs


def _core_degrees(pairs: list[tuple[str, str]]) -> dict[str, int]:
    """Distinct-neighbor degree of every five-core vertex over ``pairs``."""
    degrees = {core: 0 for core in _FIVE_CORES}
    for left, right in pairs:
        degrees[left] += 1
        degrees[right] += 1
    return degrees


def test_every_core_meets_its_link_target() -> None:
    """With three links per core, every core wires to at least three others."""
    assert min(_core_degrees(_backbone()).values()) == 3


def test_link_target_scales_with_the_config() -> None:
    """Lowering the target to two leaves the least-connected core with two links."""
    assert min(_core_degrees(_backbone(links_per_core=2)).values()) == 2


def test_a_core_wires_to_its_nearest_not_its_farthest() -> None:
    """c1's three nearest are c2/c3/c4, so it never wires the distant c5."""
    assert edge_key("c1", "c5") not in _backbone()


def test_each_core_picks_exactly_its_target_unioned() -> None:
    """Three picks per core union to nine distinct backbone links."""
    assert len(_backbone()) == 9


def test_a_core_picked_by_a_farther_peer_gains_an_extra_link() -> None:
    """c2 is among others' nearest, so it ends one over the three-link target."""
    assert _core_degrees(_backbone())["c2"] == 4


def test_a_removed_pair_gets_no_link() -> None:
    """An operator-pruned core-core pair gets no backbone link."""
    assert edge_key("c1", "c2") not in _backbone(frozenset({edge_key("c1", "c2")}))


def test_a_removed_pair_is_filled_by_the_next_nearest() -> None:
    """Dropping c1-c2 makes c1 wire to c5, its next-nearest reachable core."""
    assert edge_key("c1", "c5") in _backbone(frozenset({edge_key("c1", "c2")}))


def test_core_backbone_none_when_a_core_cannot_reach_enough_peers() -> None:
    """A core that cannot reach its target number of peers yields no selection."""
    distances = _symmetric_distances({("c1", "c2"): 1.0})
    distances["c3"] = {"c3": 0.0}
    assert select_core_backbone_pairs(("c1", "c2", "c3"), distances) is None


_UNIT_MESH_EDGES = physical({
    ("c1", "c2"): 1.0, ("c1", "c3"): 1.0, ("c1", "c4"): 1.0, ("c1", "c5"): 1.0,
    ("c2", "c3"): 1.0, ("c2", "c4"): 1.0, ("c2", "c5"): 1.0,
    ("c3", "c4"): 1.0, ("c3", "c5"): 1.0, ("c4", "c5"): 1.0,
})


def _five_core_mesh_paths(removed: frozenset[tuple[str, str]] = frozenset()) -> list[PathUse]:
    """Route the five-core backbone over a unit-weight physical graph."""
    adjacency = build_adjacency(_UNIT_MESH_EDGES)
    distances, predecessors = all_pairs_shortest([pop(c) for c in _FIVE_CORES], adjacency)
    return core_mesh_paths(
        _FIVE_CORES, distances, predecessors, _UNIT_MESH_EDGES, BackboneConstraints(removed)
    )


def test_core_mesh_paths_route_each_backbone_link() -> None:
    """The backbone routes one path per selected core link: nine over five cores."""
    assert len(_five_core_mesh_paths()) == 9


def test_core_mesh_paths_omit_a_removed_pair() -> None:
    """An operator-pruned pair gets no routed core-mesh path."""
    routed = _five_core_mesh_paths(frozenset({edge_key("c1", "c2")}))
    assert edge_key("c1", "c2") not in {edge_key(use.source, use.target) for use in routed}
