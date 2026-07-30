"""Unit tests for the validation helpers."""

from __future__ import annotations

import fixtures
import pytest

from synthesizer.input_graph import edge_key
from synthesizer.model import AccessEdge, Design, DesignMetrics
from synthesizer.validation import (
    backbone_mesh_deficient,
    backbone_mesh_independence_deficient,
    demand_backbone_homes,
    design_edge_set,
    included_vertex_ids,
    independent_mesh_degree,
    mesh_link_failure_cities,
    neighbor_degrees,
)


def make_design(
    physical_pairs: list[tuple[str, str]],
    *,
    backbone_ids: tuple[str, ...] = (),
    transit_ids: tuple[str, ...] = (),
    access_edges: list[AccessEdge] | None = None,
) -> Design:
    """Test helper: build a Design from physical pairs and tier assignments."""
    return Design(
        backbone_ids=backbone_ids,
        transit_ids=transit_ids,
        access_edges=access_edges or [],
        physical_edge_keys={edge_key(a, b) for a, b in physical_pairs},
        path_uses=[],
        metrics=DesignMetrics(0.0, 0.0, 0.0),
    )


meshed_design = fixtures.meshed_backbone_design


def test_included_vertex_ids_covers_access_endpoints() -> None:
    """Included vertex ids covers access endpoints."""
    design = make_design([("a", "b")], access_edges=[AccessEdge("s", "a", 1.0)])
    assert included_vertex_ids(design) == {"a", "b", "s"}


def test_included_vertex_ids_covers_the_tier_ids() -> None:
    """Backbone and transit ids are part of the included vertex set."""
    design = make_design([], backbone_ids=("b",), transit_ids=("t",))
    assert included_vertex_ids(design) == {"b", "t"}


def test_design_edge_set_merges_access_and_physical() -> None:
    """Design edge set merges access and physical."""
    design = make_design([("a", "b")], access_edges=[AccessEdge("s", "a", 1.0)])
    assert design_edge_set(design) == {edge_key("a", "b"), edge_key("s", "a")}


def test_neighbor_degrees_counts_distinct_neighbors() -> None:
    """Neighbor degrees counts distinct neighbors."""
    degrees = neighbor_degrees({"a", "b", "c"}, {("a", "b"), ("b", "c")})
    assert degrees == {"a": 1, "b": 2, "c": 1}


def test_neighbor_degrees_ignores_external_endpoints() -> None:
    """Neighbor degrees ignores external endpoints."""
    degrees = neighbor_degrees({"a", "b"}, {("a", "b"), ("a", "z")})
    assert degrees == {"a": 1, "b": 1}


def test_demand_backbone_homes_groups_targets_per_source() -> None:
    """Each demand vertex maps to the distinct backbone nodes it homes to."""
    design = make_design(
        [], access_edges=[AccessEdge("s", "a", 1.0), AccessEdge("s", "b", 1.0)]
    )
    assert demand_backbone_homes(design) == {"s": {"a", "b"}}


_SHARED_EGRESS = meshed_design(
    fixtures.SHARED_TRANSIT_ROUTES, fixtures.SHARED_TRANSIT_BACKBONE
)
_DIVERSE_EGRESS = meshed_design(
    fixtures.DIVERSE_TRANSIT_ROUTES, fixtures.SHARED_TRANSIT_BACKBONE
)
_MESH_VERTICES = fixtures.carrier_pops_by_id("abcxy")


def test_mesh_link_failure_cities_excludes_the_node_itself() -> None:
    """A link's failure cities are every city on its route bar the node being counted."""
    design = meshed_design([("a", "x", "b")], ("a", "b"))
    assert mesh_link_failure_cities(design, "a") == [frozenset({"x", "b"})]


def test_mesh_link_failure_cities_ignores_links_elsewhere() -> None:
    """A link neither of whose ends is the node contributes no failure cities to it."""
    design = meshed_design([("b", "x", "c")], ("a", "b", "c"))
    assert mesh_link_failure_cities(design, "a") == []


def test_mesh_link_failure_cities_counts_the_peer_as_a_city() -> None:
    """The peer at the far end is a city too, so its loss takes the link with it."""
    design = meshed_design([("a", "b")], ("a", "b"))
    assert mesh_link_failure_cities(design, "a") == [frozenset({"b"})]


@pytest.mark.parametrize("degree", [2, 3, 4])
def test_independent_mesh_degree_counts_every_city_disjoint_link(degree: int) -> None:
    """A node whose links each leave through a city of their own counts all of them."""
    peers = "bcde"[:degree]
    design = meshed_design(
        [("a", f"x{peer}", peer) for peer in peers], ("a", *peers)
    )
    assert independent_mesh_degree(design, "a") == degree


def test_independent_mesh_degree_counts_links_sharing_a_transit_city_once() -> None:
    """Two links crossing one transit city are one independent link, not two."""
    assert independent_mesh_degree(_SHARED_EGRESS, "a") == 1


def test_independent_mesh_degree_counts_a_diverse_pair_as_two() -> None:
    """Two links crossing no common city are two independent links."""
    assert independent_mesh_degree(_DIVERSE_EGRESS, "a") == 2


def test_independent_mesh_degree_of_a_node_with_no_links_is_zero() -> None:
    """A backbone node holding no mesh link has no independent links."""
    assert independent_mesh_degree(meshed_design([], ("a",)), "a") == 0


def test_independent_mesh_degree_counts_a_detour_to_one_peer_once() -> None:
    """Two routes to the same peer are one link: losing the peer city takes both."""
    design = meshed_design([("a", "x", "b"), ("a", "y", "b")], ("a", "b"))
    assert independent_mesh_degree(design, "a") == 1


# Four nodes where "a" holds one mesh link and the rest hold two, against a target of
# two: the shortfall is one node's, so an exemption either silences it or does nothing.
_MESH_DEGREES = {"a": 1, "b": 2, "c": 2, "d": 2}
_MESH_NODES = ("a", "b", "c", "d")


def test_mesh_deficient_names_the_node_below_the_degree() -> None:
    """A node under the mesh degree is reported with the count it holds."""
    vertices = fixtures.carrier_pops_by_id("abcd")
    assert backbone_mesh_deficient(_MESH_NODES, _MESH_DEGREES, vertices, 2) == [
        {"id": "a", "name": "a", "degree": 1}
    ]


def test_mesh_deficient_leaves_out_an_exempt_node() -> None:
    """The node the degree is not asked of is no longer reported as short of it."""
    vertices = fixtures.carrier_pops_by_id("abcd")
    assert backbone_mesh_deficient(
        _MESH_NODES, _MESH_DEGREES, vertices, 2, frozenset({"a"})
    ) == []


def test_mesh_deficient_still_names_a_node_that_is_not_exempt() -> None:
    """Exempting one node says nothing about another node's shortfall."""
    vertices = fixtures.carrier_pops_by_id("abcd")
    assert backbone_mesh_deficient(
        _MESH_NODES, _MESH_DEGREES, vertices, 2, frozenset({"b"})
    ) == [{"id": "a", "name": "a", "degree": 1}]


def test_independence_deficient_names_the_node_below_the_degree() -> None:
    """A node short of independently failing links is reported with the count it holds."""
    assert backbone_mesh_independence_deficient(_SHARED_EGRESS, _MESH_VERTICES, 2) == [
        {"id": "a", "name": "a", "independent_degree": 1}
    ]


def test_independence_deficient_leaves_out_an_exempt_node() -> None:
    """The chokepoint node the degree is not asked of is no longer reported."""
    assert backbone_mesh_independence_deficient(
        _SHARED_EGRESS, _MESH_VERTICES, 2, frozenset({"a"})
    ) == []


def test_independence_deficient_still_names_a_node_that_is_not_exempt() -> None:
    """Exempting another node leaves the chokepoint node reported as it was."""
    assert backbone_mesh_independence_deficient(
        _SHARED_EGRESS, _MESH_VERTICES, 2, frozenset({"b"})
    ) == [{"id": "a", "name": "a", "independent_degree": 1}]


def test_independence_deficient_passes_a_diversely_routed_mesh() -> None:
    """A mesh whose every node holds the configured independent links reports nothing."""
    assert backbone_mesh_independence_deficient(_DIVERSE_EGRESS, _MESH_VERTICES, 2) == []


@pytest.mark.parametrize("degree", [2, 3, 4])
def test_independence_deficient_is_empty_when_the_backbone_is_too_small(
    degree: int,
) -> None:
    """A backbone no larger than the degree cannot meet it, so nothing is reported."""
    backbone = "abcd"[:degree]
    design = meshed_design([], tuple(backbone))
    vertices = fixtures.carrier_pops_by_id(backbone)
    assert backbone_mesh_independence_deficient(design, vertices, degree) == []
