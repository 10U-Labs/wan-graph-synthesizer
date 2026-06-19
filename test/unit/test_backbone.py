"""Unit tests for core-backbone selection, routing, and degree thinning."""

from __future__ import annotations

import itertools

import fixtures
from wan_designer.model import (
    PathUse,
    edge_key,
)
from wan_designer.backbone import (
    BackboneConstraints,
    core_mesh_paths,
    select_core_backbone_pairs,
    _thin_to_max_degree,
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


def _full_mesh(removed: frozenset[tuple[str, str]] = frozenset()) -> list[tuple[str, str]]:
    """The core backbone over the five-core mesh, minus ``removed`` (asserted reachable)."""
    pairs = select_core_backbone_pairs(_FIVE_CORES, _FIVE_CORE_DISTANCES, removed)
    assert pairs is not None
    return pairs


def test_core_backbone_is_the_full_mesh() -> None:
    """Every core pair gets a backbone link: the full mesh of C(5, 2) = 10 links."""
    assert len(_full_mesh()) == 10


def test_core_backbone_omits_a_removed_pair() -> None:
    """An operator-pruned core-core pair gets no backbone link."""
    assert edge_key("c1", "c5") not in _full_mesh(frozenset({edge_key("c1", "c5")}))


def test_core_backbone_keeps_the_other_pairs_when_one_is_removed() -> None:
    """Pruning one pair drops exactly that link: nine of the ten mesh links remain."""
    assert len(_full_mesh(frozenset({edge_key("c1", "c5")}))) == 9


def _core_degrees(pairs: list[tuple[str, str]]) -> dict[str, int]:
    """Distinct-neighbor degree of every five-core vertex over ``pairs``."""
    degrees = {core: 0 for core in _FIVE_CORES}
    for left, right in pairs:
        degrees[left] += 1
        degrees[right] += 1
    return degrees


def _capped(max_degree: int) -> list[tuple[str, str]]:
    """The five-core backbone thinned to ``max_degree`` links per core (asserted reachable)."""
    pairs = select_core_backbone_pairs(_FIVE_CORES, _FIVE_CORE_DISTANCES, max_degree=max_degree)
    assert pairs is not None
    return pairs


def test_core_backbone_cap_at_the_mesh_degree_keeps_the_full_mesh() -> None:
    """A cap at the full-mesh degree (n-1) binds on no core, so all ten links stay."""
    assert len(_capped(4)) == 10


def test_core_backbone_cap_drops_the_longest_over_limit_links() -> None:
    """Capping degree at three drops the longest over-limit link and leaves eight links."""
    capped = _capped(3)
    assert edge_key("c1", "c5") not in capped and len(capped) == 8


def test_core_backbone_cap_holds_the_floor_for_the_least_connected_core() -> None:
    """Thinning never drops a core below the floor of three backbone links."""
    assert min(_core_degrees(_capped(3)).values()) == 3


def test_core_backbone_cap_is_best_effort_above_the_floor() -> None:
    """K5 cannot reach a cap of three everywhere, so one core stays at four (best-effort)."""
    assert max(_core_degrees(_capped(3)).values()) == 4


# Two K4 blocks joined by a single bridge link: the bridge endpoints sit one over a
# cap of three, but dropping the bridge would split the backbone in two.
_BRIDGE_CORES = ("a", "b", "c", "d", "e", "f", "g", "h")
_BRIDGE_PAIRS = [
    edge_key(left, right)
    for block in (("a", "b", "c", "d"), ("e", "f", "g", "h"))
    for left, right in itertools.combinations(block, 2)
] + [edge_key("a", "e")]
_BRIDGE_DISTANCES = _symmetric_distances(
    {pair: (100.0 if pair == edge_key("a", "e") else 1.0) for pair in _BRIDGE_PAIRS}
)


def test_thinning_keeps_a_link_whose_loss_breaks_two_edge_connectivity() -> None:
    """A bridge over the cap is kept: dropping it would disconnect the backbone."""
    result = _thin_to_max_degree(_BRIDGE_CORES, _BRIDGE_PAIRS, _BRIDGE_DISTANCES, 3)
    assert set(result) == set(_BRIDGE_PAIRS)


def test_core_backbone_none_when_a_kept_core_pair_is_unreachable() -> None:
    """A kept core pair unreachable over the carrier graph yields no backbone selection."""
    distances = _symmetric_distances({("c1", "c2"): 1.0})
    assert select_core_backbone_pairs(("c1", "c2", "c3"), distances) is None


_UNIT_MESH_EDGES = physical({
    ("c1", "c2"): 1.0, ("c1", "c3"): 1.0, ("c1", "c4"): 1.0, ("c1", "c5"): 1.0,
    ("c2", "c3"): 1.0, ("c2", "c4"): 1.0, ("c2", "c5"): 1.0,
    ("c3", "c4"): 1.0, ("c3", "c5"): 1.0, ("c4", "c5"): 1.0,
})


def _five_core_mesh_paths(removed: frozenset[tuple[str, str]] = frozenset()) -> list[PathUse]:
    """Route the five-core backbone over a mileage-weighted full-mesh graph."""
    adjacency = build_adjacency(_UNIT_MESH_EDGES)
    distances, predecessors = all_pairs_shortest([pop(c) for c in _FIVE_CORES], adjacency)
    return core_mesh_paths(
        _FIVE_CORES, distances, predecessors, _UNIT_MESH_EDGES, BackboneConstraints(removed)
    )


def test_core_mesh_paths_route_the_full_mesh() -> None:
    """The backbone routes one path per core pair: the full mesh of ten links."""
    assert len(_five_core_mesh_paths()) == 10


def test_core_mesh_paths_omit_a_removed_pair() -> None:
    """An operator-pruned pair gets no routed core-mesh path."""
    routed = _five_core_mesh_paths(frozenset({edge_key("c1", "c2")}))
    assert edge_key("c1", "c2") not in {edge_key(use.source, use.target) for use in routed}
