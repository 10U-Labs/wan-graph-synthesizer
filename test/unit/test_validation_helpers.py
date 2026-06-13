"""Unit tests for validation helpers and the resilience augmentation pass."""

from __future__ import annotations

import fixtures
from wan_designer.model import (
    AccessEdge,
    Design,
    DesignMetrics,
    Node,
    edge_key,
)
from wan_designer.validation import (
    access_attachment_counts,
    augment_physical_resilience,
    best_edge_to_add,
    design_badness,
    design_edge_set,
    disconnected_core_pairs,
    included_node_ids,
    neighbor_degrees,
    node_role,
    refresh_physical_costs,
    with_updated_physical_edges,
)


def pop(node_id: str) -> Node:
    """Test helper: build a carrier PoP node."""
    return Node(
        id=node_id, name=node_id, category="c", kind="carrier_pop", lat=0.0, lon=0.0
    )


def make_design(
    physical_pairs: list[tuple[str, str]],
    *,
    core_ids: tuple[str, ...] = (),
    aggregation_ids: tuple[str, ...] = (),
    transit_ids: tuple[str, ...] = (),
    access_edges: list[AccessEdge] | None = None,
) -> Design:
    """Test helper: build a Design from physical pairs and tier assignments."""
    return Design(
        core_ids=core_ids,
        aggregation_ids=aggregation_ids,
        transit_ids=transit_ids,
        access_edges=access_edges or [],
        physical_edge_keys={edge_key(a, b) for a, b in physical_pairs},
        path_uses=[],
        metrics=DesignMetrics(0.0, 0.0, 0.0),
    )


PATH_DESIGN = make_design([("a", "b"), ("b", "c")], transit_ids=("a", "b", "c"))
PATH_NODES = [pop("a"), pop("b"), pop("c")]


def test_node_role_access_for_non_pop() -> None:
    """Node role access for non pop."""
    access = Node(id="s", name="s", category="F-35", kind="f35", lat=0.0, lon=0.0)
    assert node_role("s", make_design([]), access) == "access"


def test_node_role_core() -> None:
    """Node role core."""
    design = make_design([], core_ids=("a",))
    assert node_role("a", design, pop("a")) == "core"


def test_node_role_aggregation() -> None:
    """Node role aggregation."""
    design = make_design([], aggregation_ids=("a",))
    assert node_role("a", design, pop("a")) == "aggregation"


def test_node_role_transit() -> None:
    """Node role transit."""
    design = make_design([], transit_ids=("a",))
    assert node_role("a", design, pop("a")) == "transit"


def test_node_role_unused() -> None:
    """Node role unused."""
    assert node_role("a", make_design([]), pop("a")) == "unused"


def test_included_node_ids_covers_access_endpoints() -> None:
    """Included node ids covers access endpoints."""
    design = make_design([("a", "b")], access_edges=[AccessEdge("s", "a", 1.0)])
    assert included_node_ids(design) == {"a", "b", "s"}


def test_design_edge_set_merges_access_and_physical() -> None:
    """Design edge set merges access and physical."""
    design = make_design([("a", "b")], access_edges=[AccessEdge("s", "a", 1.0)])
    assert design_edge_set(design) == {edge_key("a", "b"), edge_key("s", "a")}


def test_neighbor_degrees_counts_distinct_neighbors() -> None:
    """Neighbor degrees counts distinct neighbors."""
    degrees = neighbor_degrees({"a", "b", "c"}, {("a", "b"), ("b", "c")})
    assert degrees == {"a": 1, "b": 2, "c": 1}


def test_access_attachment_counts_per_source() -> None:
    """Access attachment counts per source."""
    design = make_design(
        [], access_edges=[AccessEdge("s", "a", 1.0), AccessEdge("s", "b", 1.0)]
    )
    assert access_attachment_counts(design) == {"s": 2}


def test_design_badness_flags_articulation_and_degree() -> None:
    """Design badness flags articulation and degree."""
    assert design_badness(PATH_NODES, PATH_DESIGN) == (0, 1, 2)


def test_with_updated_physical_edges_recomputes_transit() -> None:
    """With updated physical edges recomputes transit."""
    updated = with_updated_physical_edges(PATH_DESIGN, {edge_key("a", "b")})
    assert updated.transit_ids == ("a", "b")


def test_refresh_physical_costs_sums_distances() -> None:
    """Refresh physical costs sums distances."""
    edges = fixtures.physical_edges_from({("a", "b"): 3.0, ("b", "c"): 4.0})
    refreshed = refresh_physical_costs(edges, PATH_DESIGN)
    assert refreshed.metrics.physical_miles == 7.0


def test_best_edge_to_add_returns_none_when_no_improvement() -> None:
    """Best edge to add returns none when no improvement."""
    edges = fixtures.physical_edges_from({("a", "b"): 1.0, ("b", "c"): 1.0})
    key, _badness = best_edge_to_add(PATH_NODES, edges, PATH_DESIGN, (0, 1, 2))
    assert key is None


def test_best_edge_to_add_picks_the_fixing_edge() -> None:
    """Best edge to add picks the fixing edge."""
    edges = fixtures.physical_edges_from({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 5.0})
    key, _badness = best_edge_to_add(PATH_NODES, edges, PATH_DESIGN, (0, 1, 2))
    assert key == edge_key("a", "c")


def test_augment_adds_edge_to_remove_articulation() -> None:
    """Augment adds edge to remove articulation."""
    edges = fixtures.physical_edges_from({("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 5.0})
    result = augment_physical_resilience(PATH_NODES, edges, PATH_DESIGN)
    assert edge_key("a", "c") in result.physical_edge_keys


def test_augment_stops_when_no_edge_helps() -> None:
    """Augment stops when no edge helps."""
    edges = fixtures.physical_edges_from({("a", "b"): 1.0, ("b", "c"): 1.0})
    result = augment_physical_resilience(PATH_NODES, edges, PATH_DESIGN)
    assert result.physical_edge_keys == {edge_key("a", "b"), edge_key("b", "c")}


def test_best_edge_to_add_skips_a_worsening_candidate() -> None:
    """Best edge to add skips a worsening candidate."""
    nodes = PATH_NODES + [pop("d")]
    edges = fixtures.physical_edges_from(
        {("a", "b"): 1.0, ("b", "c"): 1.0, ("a", "c"): 5.0, ("c", "d"): 1.0}
    )
    key, _badness = best_edge_to_add(nodes, edges, PATH_DESIGN, (0, 1, 2))
    assert key == edge_key("a", "c")


PATH4_DESIGN = make_design(
    [("a", "b"), ("b", "c"), ("c", "d")], transit_ids=("a", "b", "c", "d")
)
PATH4_NODES = [pop("a"), pop("b"), pop("c"), pop("d")]


def test_best_edge_to_add_keeps_the_stronger_of_two_improvers() -> None:
    """Best edge to add keeps the stronger of two improvers."""
    edges = fixtures.physical_edges_from(
        {
            ("a", "b"): 1.0,
            ("b", "c"): 1.0,
            ("c", "d"): 1.0,
            ("a", "d"): 2.0,
            ("a", "c"): 2.0,
        }
    )
    key, _badness = best_edge_to_add(PATH4_NODES, edges, PATH4_DESIGN, (0, 2, 2))
    assert key == edge_key("a", "d")


def test_disconnected_core_pairs_flags_core_without_edges() -> None:
    """Disconnected core pairs flags core without edges."""
    design = make_design([("c2", "x")], core_ids=("c1", "c2"))
    assert disconnected_core_pairs(design) == [("c1", "c2")]


def test_neighbor_degrees_ignores_external_endpoints() -> None:
    """Neighbor degrees ignores external endpoints."""
    degrees = neighbor_degrees({"a", "b"}, {("a", "b"), ("a", "z")})
    assert degrees == {"a": 1, "b": 1}
