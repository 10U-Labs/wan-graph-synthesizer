"""Unit tests for the validation helpers."""

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
    """Test helper: build a Synthesis from physical pairs and tier assignments."""
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
    """Included site ids covers access endpoints."""
    synthesis = make_synthesis([("a", "b")], access_paths=[AccessPath("s", "a", 1.0)])
    assert included_site_ids(synthesis) == {"a", "b", "s"}


def test_included_site_ids_covers_the_tier_ids() -> None:
    """Backbone and transit ids are part of the included site set."""
    synthesis = make_synthesis([], backbone_ids=("b",), transit_ids=("t",))
    assert included_site_ids(synthesis) == {"b", "t"}


def test_synthesis_link_keys_merges_access_and_physical() -> None:
    """Synthesis link set merges access and physical."""
    synthesis = make_synthesis([("a", "b")], access_paths=[AccessPath("s", "a", 1.0)])
    assert synthesis_link_keys(synthesis) == {link_key("a", "b"), link_key("s", "a")}


def test_neighbor_degrees_counts_distinct_neighbors() -> None:
    """Neighbor degrees counts distinct neighbors."""
    degrees = neighbor_degrees({"a", "b", "c"}, {("a", "b"), ("b", "c")})
    assert degrees == {"a": 1, "b": 2, "c": 1}


def test_neighbor_degrees_ignores_external_endpoints() -> None:
    """Neighbor degrees ignores external endpoints."""
    degrees = neighbor_degrees({"a", "b"}, {("a", "b"), ("a", "z")})
    assert degrees == {"a": 1, "b": 1}


def test_demand_backbone_homes_groups_targets_per_source() -> None:
    """Each demand site maps to the distinct backbone nodes it homes to."""
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
    """A link's failure cities are every city on its path bar the node being counted."""
    synthesis = meshed_synthesis([("a", "x", "b")], ("a", "b"))
    assert mesh_link_failure_cities(synthesis, "a") == [frozenset({"x", "b"})]


def test_mesh_link_failure_cities_ignores_links_elsewhere() -> None:
    """A link neither of whose ends is the node contributes no failure cities to it."""
    synthesis = meshed_synthesis([("b", "x", "c")], ("a", "b", "c"))
    assert mesh_link_failure_cities(synthesis, "a") == []


def test_mesh_link_failure_cities_counts_the_peer_as_a_city() -> None:
    """The peer at the far end is a city too, so its loss takes the link with it."""
    synthesis = meshed_synthesis([("a", "b")], ("a", "b"))
    assert mesh_link_failure_cities(synthesis, "a") == [frozenset({"b"})]


@pytest.mark.parametrize("degree", [2, 3, 4])
def test_diverse_path_count_counts_every_city_disjoint_link(degree: int) -> None:
    """A node whose links each leave through a city of their own counts all of them."""
    peers = "bcde"[:degree]
    synthesis = meshed_synthesis(
        [("a", f"x{peer}", peer) for peer in peers], ("a", *peers)
    )
    assert diverse_path_count(synthesis.path_uses, "a") == degree


def test_diverse_path_count_counts_links_sharing_a_transit_city_once() -> None:
    """Two links crossing one transit city are one independent link, not two."""
    assert diverse_path_count(_SHARED_EGRESS.path_uses, "a") == 1


def test_diverse_path_count_counts_a_diverse_pair_as_two() -> None:
    """Two links crossing no common city are two independent links."""
    assert diverse_path_count(_DIVERSE_EGRESS.path_uses, "a") == 2


def test_diverse_path_count_of_a_node_with_no_links_is_zero() -> None:
    """A backbone node holding no mesh link has no independent links."""
    assert diverse_path_count(meshed_synthesis([], ("a",)).path_uses, "a") == 0


def test_diverse_path_count_counts_two_paths_to_the_only_peer_as_two() -> None:
    """A two-site backbone gets its two paths as two paths to the one peer there is.

    Losing ``b`` takes both, and takes the destination with them: the site has lost what it
    was reaching for rather than the protection on the way. Counting these once is what left
    Two-Node published with five paths and reported as meeting a target of one
    (GitHub issue #58).
    """
    synthesis = meshed_synthesis([("a", "x", "b"), ("a", "y", "b")], ("a", "b"))
    assert diverse_path_count(synthesis.path_uses, "a") == 2


def test_diverse_path_count_counts_a_link_crossing_a_peer_with_that_peers_link_once() -> None:
    """A direct link to b and a link crossing b both fall with b, so they are one way out.

    The peer two links share is theirs to share only when both of them end there. Here one
    ends at ``b`` and the other passes through it on the way to ``c``, so ``b`` is a transit
    city on the second and the pair is no more independent than any other pair sharing one.
    """
    synthesis = meshed_synthesis([("a", "b"), ("a", "b", "c")], ("a", "b", "c"))
    assert diverse_path_count(synthesis.path_uses, "a") == 1


# Four nodes where "a" holds one mesh link and the rest hold two, against a target of
# two: the shortfall is one node's, so an exemption either silences it or does nothing.
_MESH_DEGREES = {"a": 1, "b": 2, "c": 2, "d": 2}
_MESH_NODES = ("a", "b", "c", "d")


def test_mesh_deficient_names_the_node_below_the_degree() -> None:
    """A node under the diverse path count is reported with the count it holds."""
    sites = fixtures.carrier_pops_by_id("abcd")
    assert backbone_mesh_deficient(_MESH_NODES, _MESH_DEGREES, sites, MeshRequirements(2)) == [
        {"id": "a", "name": "a", "degree": 1}
    ]


def test_mesh_deficient_leaves_out_an_exempt_node() -> None:
    """The node the degree is not asked of is no longer reported as short of it."""
    sites = fixtures.carrier_pops_by_id("abcd")
    assert backbone_mesh_deficient(
        _MESH_NODES, _MESH_DEGREES, sites, MeshRequirements(2, frozenset({"a"}))
    ) == []


def test_mesh_deficient_still_names_a_node_that_is_not_exempt() -> None:
    """Exempting one node says nothing about another node's shortfall."""
    sites = fixtures.carrier_pops_by_id("abcd")
    assert backbone_mesh_deficient(
        _MESH_NODES, _MESH_DEGREES, sites, MeshRequirements(2, frozenset({"b"}))
    ) == [{"id": "a", "name": "a", "degree": 1}]


def test_mesh_deficient_holds_a_capped_node_to_its_ceiling() -> None:
    """The nominal count uses the same per-node target, so the two cannot disagree."""
    sites = fixtures.carrier_pops_by_id("abcd")
    assert backbone_mesh_deficient(
        _MESH_NODES, _MESH_DEGREES, sites, MeshRequirements(2, ceilings={"a": 1})
    ) == []


def test_independence_deficient_names_the_node_below_the_degree() -> None:
    """A node short of independently failing links is reported with the count it holds."""
    assert backbone_mesh_independence_deficient(
        _SHARED_EGRESS, _MESH_SITES, MeshRequirements(2)
    ) == [
        {"id": "a", "name": "a", "independent_degree": 1}
    ]


def test_independence_deficient_leaves_out_an_exempt_node() -> None:
    """The single point of failure node the degree is not asked of is no longer reported."""
    assert backbone_mesh_independence_deficient(
        _SHARED_EGRESS, _MESH_SITES, MeshRequirements(2, frozenset({"a"}))
    ) == []


def test_independence_deficient_still_names_a_node_that_is_not_exempt() -> None:
    """Exempting another node leaves the single point of failure node reported as it was."""
    assert backbone_mesh_independence_deficient(
        _SHARED_EGRESS, _MESH_SITES, MeshRequirements(2, frozenset({"b"}))
    ) == [{"id": "a", "name": "a", "independent_degree": 1}]


def test_independence_deficient_passes_a_diversely_drawn_mesh() -> None:
    """A mesh whose every node holds the configured independent links reports nothing."""
    assert backbone_mesh_independence_deficient(
        _DIVERSE_EGRESS, _MESH_SITES, MeshRequirements(2)
    ) == []


def test_independence_deficient_holds_a_capped_node_to_its_ceiling() -> None:
    """One link is all a's fiber allows, so the one it holds is not a shortfall."""
    assert backbone_mesh_independence_deficient(
        _SHARED_EGRESS, _MESH_SITES, MeshRequirements(2, ceilings={"a": 1})
    ) == []


def test_independence_deficient_still_names_a_node_under_its_own_ceiling() -> None:
    """a's fiber allows the two asked of it, so holding one is the tool's defect to report."""
    assert backbone_mesh_independence_deficient(
        _SHARED_EGRESS, _MESH_SITES, MeshRequirements(2, ceilings={"a": 2})
    ) == [{"id": "a", "name": "a", "independent_degree": 1}]


@pytest.mark.parametrize("degree", [2, 3, 4])
def test_independence_deficient_still_asks_a_backbone_no_larger_than_the_degree(
    degree: int,
) -> None:
    """A small backbone is measured too, since its sites double up on peers to make the number.

    This used to return empty on the reasoning that a site cannot hold more paths than it
    has peers to reach. A peer may now carry more than one path, so the reasoning no longer
    holds and the check that rested on it waved Two-Node through unmeasured
    (GitHub issue #58). Every site here holds no link at all, so every one of them is short.
    """
    backbone = "abcd"[:degree]
    synthesis = meshed_synthesis([], tuple(backbone))
    sites = fixtures.carrier_pops_by_id(backbone)
    assert [
        row["id"]
        for row in backbone_mesh_independence_deficient(
            synthesis, sites, MeshRequirements(degree)
        )
    ] == list(backbone)
