from __future__ import annotations

import fixtures
import pytest

from synthesizer.input_graph import link_key
from synthesizer.model import AccessPath, Synthesis, SynthesisMetrics, MeshRequirements
from synthesizer.validation import (
    backbone_mesh_deficient,
    backbone_mesh_independence_deficient,
    demand_backbone_homes,
    synthesis_link_keys,
    included_site_ids,
    diverse_path_count,
    mesh_link_failure_cities,
    neighbor_degrees,
)


def make_synthesis(
    physical_pairs: list[tuple[str, str]],
    *,
    backbone_ids: tuple[str, ...] = (),
    transit_ids: tuple[str, ...] = (),
    access_paths: list[AccessPath] | None = None,
) -> Synthesis:
    return Synthesis(
        backbone_ids=backbone_ids,
        transit_ids=transit_ids,
        access_paths=access_paths or [],
        fiber_segment_keys={link_key(a, b) for a, b in physical_pairs},
        path_uses=[],
        metrics=SynthesisMetrics(0.0, 0.0, 0.0),
    )


meshed_synthesis = fixtures.meshed_backbone_synthesis


def test_included_site_ids_covers_access_endpoints() -> None:
    synthesis = make_synthesis([("a", "b")], access_paths=[AccessPath("s", "a", 1.0)])
    assert included_site_ids(synthesis) == {"a", "b", "s"}


def test_included_site_ids_covers_the_tier_ids() -> None:
    synthesis = make_synthesis([], backbone_ids=("b",), transit_ids=("t",))
    assert included_site_ids(synthesis) == {"b", "t"}


def test_synthesis_link_keys_merges_access_and_physical() -> None:
    synthesis = make_synthesis([("a", "b")], access_paths=[AccessPath("s", "a", 1.0)])
    assert synthesis_link_keys(synthesis) == {link_key("a", "b"), link_key("s", "a")}


def test_neighbor_degrees_counts_distinct_neighbors() -> None:
    degrees = neighbor_degrees({"a", "b", "c"}, {("a", "b"), ("b", "c")})
    assert degrees == {"a": 1, "b": 2, "c": 1}


def test_neighbor_degrees_ignores_external_endpoints() -> None:
    degrees = neighbor_degrees({"a", "b"}, {("a", "b"), ("a", "z")})
    assert degrees == {"a": 1, "b": 1}


def test_demand_backbone_homes_groups_targets_per_source() -> None:
    synthesis = make_synthesis(
        [], access_paths=[AccessPath("s", "a", 1.0), AccessPath("s", "b", 1.0)]
    )
    assert demand_backbone_homes(synthesis) == {"s": {"a", "b"}}


_SHARED_EGRESS = meshed_synthesis(
    fixtures.SHARED_TRANSIT_PATHS, fixtures.SHARED_TRANSIT_BACKBONE
)
_DIVERSE_EGRESS = meshed_synthesis(
    fixtures.DIVERSE_TRANSIT_PATHS, fixtures.SHARED_TRANSIT_BACKBONE
)
_MESH_SITES = fixtures.carrier_pops_by_id("abcxy")


def test_mesh_link_failure_cities_excludes_the_node_itself() -> None:
    synthesis = meshed_synthesis([("a", "x", "b")], ("a", "b"))
    assert mesh_link_failure_cities(synthesis, "a") == [frozenset({"x", "b"})]


def test_mesh_link_failure_cities_ignores_links_elsewhere() -> None:
    synthesis = meshed_synthesis([("b", "x", "c")], ("a", "b", "c"))
    assert mesh_link_failure_cities(synthesis, "a") == []


def test_mesh_link_failure_cities_counts_the_peer_as_a_city() -> None:
    synthesis = meshed_synthesis([("a", "b")], ("a", "b"))
    assert mesh_link_failure_cities(synthesis, "a") == [frozenset({"b"})]


@pytest.mark.parametrize("degree", [2, 3, 4])
def test_diverse_path_count_counts_every_city_disjoint_link(degree: int) -> None:
    peers = "bcde"[:degree]
    synthesis = meshed_synthesis(
        [("a", f"x{peer}", peer) for peer in peers], ("a", *peers)
    )
    assert diverse_path_count(synthesis.path_uses, "a") == degree


def test_diverse_path_count_counts_links_sharing_a_transit_city_once() -> None:
    assert diverse_path_count(_SHARED_EGRESS.path_uses, "a") == 1


def test_diverse_path_count_counts_a_diverse_pair_as_two() -> None:
    assert diverse_path_count(_DIVERSE_EGRESS.path_uses, "a") == 2


def test_diverse_path_count_of_a_node_with_no_links_is_zero() -> None:
    assert diverse_path_count(meshed_synthesis([], ("a",)).path_uses, "a") == 0


def test_diverse_path_count_counts_two_paths_to_the_only_peer_as_two() -> None:
    synthesis = meshed_synthesis([("a", "x", "b"), ("a", "y", "b")], ("a", "b"))
    assert diverse_path_count(synthesis.path_uses, "a") == 2


def test_diverse_path_count_counts_a_link_crossing_a_peer_with_that_peers_link_once() -> None:
    synthesis = meshed_synthesis([("a", "b"), ("a", "b", "c")], ("a", "b", "c"))
    assert diverse_path_count(synthesis.path_uses, "a") == 1


_MESH_DEGREES = {"a": 1, "b": 2, "c": 2, "d": 2}
_MESH_NODES = ("a", "b", "c", "d")


def test_mesh_deficient_names_the_node_below_the_degree() -> None:
    sites = fixtures.carrier_pops_by_id("abcd")
    assert backbone_mesh_deficient(_MESH_NODES, _MESH_DEGREES, sites, MeshRequirements(2)) == [
        {"id": "a", "name": "a", "degree": 1}
    ]


def test_mesh_deficient_leaves_out_an_exempt_node() -> None:
    sites = fixtures.carrier_pops_by_id("abcd")
    assert backbone_mesh_deficient(
        _MESH_NODES, _MESH_DEGREES, sites, MeshRequirements(2, frozenset({"a"}))
    ) == []


def test_mesh_deficient_still_names_a_node_that_is_not_exempt() -> None:
    sites = fixtures.carrier_pops_by_id("abcd")
    assert backbone_mesh_deficient(
        _MESH_NODES, _MESH_DEGREES, sites, MeshRequirements(2, frozenset({"b"}))
    ) == [{"id": "a", "name": "a", "degree": 1}]


def test_mesh_deficient_holds_a_capped_node_to_its_ceiling() -> None:
    sites = fixtures.carrier_pops_by_id("abcd")
    assert backbone_mesh_deficient(
        _MESH_NODES, _MESH_DEGREES, sites, MeshRequirements(2, ceilings={"a": 1})
    ) == []


def test_independence_deficient_names_the_node_below_the_degree() -> None:
    assert backbone_mesh_independence_deficient(
        _SHARED_EGRESS, _MESH_SITES, MeshRequirements(2)
    ) == [
        {"id": "a", "name": "a", "independent_degree": 1}
    ]


def test_independence_deficient_leaves_out_an_exempt_node() -> None:
    assert backbone_mesh_independence_deficient(
        _SHARED_EGRESS, _MESH_SITES, MeshRequirements(2, frozenset({"a"}))
    ) == []


def test_independence_deficient_still_names_a_node_that_is_not_exempt() -> None:
    assert backbone_mesh_independence_deficient(
        _SHARED_EGRESS, _MESH_SITES, MeshRequirements(2, frozenset({"b"}))
    ) == [{"id": "a", "name": "a", "independent_degree": 1}]


def test_independence_deficient_passes_a_diversely_drawn_mesh() -> None:
    assert backbone_mesh_independence_deficient(
        _DIVERSE_EGRESS, _MESH_SITES, MeshRequirements(2)
    ) == []


def test_independence_deficient_holds_a_capped_node_to_its_ceiling() -> None:
    assert backbone_mesh_independence_deficient(
        _SHARED_EGRESS, _MESH_SITES, MeshRequirements(2, ceilings={"a": 1})
    ) == []


def test_independence_deficient_still_names_a_node_under_its_own_ceiling() -> None:
    assert backbone_mesh_independence_deficient(
        _SHARED_EGRESS, _MESH_SITES, MeshRequirements(2, ceilings={"a": 2})
    ) == [{"id": "a", "name": "a", "independent_degree": 1}]


@pytest.mark.parametrize("degree", [2, 3, 4])
def test_independence_deficient_still_asks_a_backbone_no_larger_than_the_degree(
    degree: int,
) -> None:
    backbone = "abcd"[:degree]
    synthesis = meshed_synthesis([], tuple(backbone))
    sites = fixtures.carrier_pops_by_id(backbone)
    assert [
        row["id"]
        for row in backbone_mesh_independence_deficient(
            synthesis, sites, MeshRequirements(degree)
        )
    ] == list(backbone)
