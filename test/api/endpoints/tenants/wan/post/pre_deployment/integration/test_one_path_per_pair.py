"""Integration test: how many paths a whole synthesis buys between one pair of sites.

Two sites that are joined are joined once. A second path between the same two sites is a
second path somebody orders every month, and it buys nothing the first did not: what
makes a site's ways out independent is that they end at different peers. A pair is joined
twice only where nothing else is left -- a tenant whose config seats two sites, which has
its own file beside this one, or a site whose fiber offers no other way out at all.

The shape that overbuilds a pair cannot be made from a clique or a ring, which is why this
tier missed it. It needs the two ends of a pair to prove different fiber to each other, and
they do that when the cheapest way out of one site is already spoken for by another of its
peers. ``fixtures.SHARED_HUB_PEER_EDGES`` is that graph: three sites over three shared hub
cities where b and c each proved their own way to the other, five hundred miles apart, and
a fourth site d joined to b and to c over fiber of its own.

The fourth site is what the argument turns on. Joined once, b's links to a and to c both
ride ``h1``, and the path to d is the second way out that no one city takes with them --
so the money that was buying b a second path to c buys a path to a site b did not
reach at all. That is the network being argued for, and it is the reason the pair is not
joined twice here (GitHub issue #59).

The hub and corridor cities are not data-center cities, so none of them can take a backbone
seat and the backbone stays the four sites the case is about.
"""

from __future__ import annotations

import fixtures
from synthesizer.input_graph import edge_key

ARTIFACTS = fixtures.shared_hub_peer_artifacts()
_MESH = [use for use in ARTIFACTS.design.path_uses if use.purpose == "backbone_mesh"]


def _paths_per_pair() -> dict[tuple[str, str], int]:
    """How many paths the finished design drew between each pair of backbone sites.

    Counted off the drawn paths rather than through
    ``synthesizer.validation.backbone_mesh_pairs``, which answers with a set: a pair drawn
    twice collapses into the one member it is, so the count of pairs reads the same whether
    the design bought one path between them or two.
    """
    drawn: dict[tuple[str, str], int] = {}
    for use in _MESH:
        pair = edge_key(use.source, use.target)
        drawn[pair] = drawn.get(pair, 0) + 1
    return drawn


def test_the_backbone_is_the_four_sites() -> None:
    """Only the sites sit at data-center cities, so no hub or corridor city takes a seat."""
    assert sorted(ARTIFACTS.design.backbone_ids) == ["a", "b", "c", "d"]


def test_no_pair_of_sites_is_joined_more_than_once() -> None:
    """b and c proved different fiber to each other, and one path is what is built."""
    assert max(_paths_per_pair().values()) == 1


def test_the_pair_whose_ends_disagreed_takes_the_shorter_of_the_two_paths() -> None:
    """Two hundred miles through h1 rather than five hundred through h3."""
    drawn = [use for use in _MESH if edge_key(use.source, use.target) == edge_key("b", "c")]
    assert drawn[0].path == ("b", "h1", "c")


def test_every_pair_the_sites_reached_for_is_still_joined() -> None:
    """Drawing a pair once is not drawing it none: the five pairs the mesh picked are wired."""
    assert len(_paths_per_pair()) == 5


def test_every_site_still_holds_the_paths_its_tenant_asked_for() -> None:
    """b rides h1 for two of its three links and reaches d clear of it, which is two ways out."""
    assert ARTIFACTS.validation["backbone_mesh_independence_deficient"] == []


def test_the_fiber_survives_the_loss_of_any_one_city() -> None:
    """No city is left carrying the whole network, so the repair pass adds no detour."""
    assert ARTIFACTS.validation["biconnected_no_articulation_points"]
