"""Integration test: how many paths a whole synthesis draws between one pair of sites.

Two sites that are joined are joined once. A second path between the same two sites is a
second path somebody orders every month, and it gains nothing the first did not: what makes
a site's ways out independent is that they end at different peers. A pair is joined twice
only where nothing else is left -- a tenant whose config seats two sites, which has its own
file beside this one, or a site whose fiber offers no other way out at all.

The shape that overbuilds a pair cannot be made from a clique or a ring, which is why this
tier missed it. It needs the two ends of a pair to prove different fiber to each other, and
they do that when the shortest way out of one site is already spoken for by another of its
peers. ``fixtures.SHARED_HUB_PEER_LINKS`` is that graph: three sites over three shared hub
cities where b and c each proved their own way to the other, five hundred miles apart, and
a fourth site d joined to b and to c over fiber of its own.

The fourth site is what the argument turns on. It is the reason b's second way out is a
path to a site it did not reach at all rather than a second path to c (GitHub issue #59).
GitHub issue #60 then took the argument one step further: choosing the fiber for the whole
synthesis at once selects eight segments and sixteen hundred miles, and over that fiber b and c
reach each other round the ring rather than over fiber of their own, so the pair is not
joined at all. Nobody loses by it -- both still hold the two ways out they were owed --
and the pair that used to be joined twice is now joined none, which is the same argument
run to the end.

The hub and corridor cities are barred from the backbone, so none of them can take a
seat and the backbone stays the four sites the case is about.
"""

from __future__ import annotations

import fixtures
from synthesizer.backbone import _needed
from synthesizer.input_graph import link_key

_ASKED_FOR = 2
ARTIFACTS = fixtures.shared_hub_peer_artifacts()
_MESH = fixtures.mesh_paths(ARTIFACTS)


def _paths_per_pair() -> dict[tuple[str, str], int]:
    """How many paths the finished synthesis drew between each pair of backbone sites.

    Counted off the drawn paths rather than through
    ``synthesizer.validation.backbone_mesh_pairs``, which answers with a set: a pair drawn
    twice collapses into the one member it is, so the count of pairs reads the same whether
    the synthesis drew one path between them or two.
    """
    drawn: dict[tuple[str, str], int] = {}
    for use in _MESH:
        pair = link_key(use.source, use.target)
        drawn[pair] = drawn.get(pair, 0) + 1
    return drawn


def test_the_backbone_is_the_four_sites() -> None:
    """The hub and corridor cities are barred, so none of them takes a seat."""
    assert sorted(ARTIFACTS.synthesis.backbone_ids) == ["a", "b", "c", "d"]


def test_no_pair_of_sites_is_joined_more_than_once() -> None:
    """b and c proved different fiber to each other, and neither path is drawn twice over."""
    assert max(_paths_per_pair().values()) == 1


def test_the_synthesis_joins_each_site_to_the_two_peers_it_reaches() -> None:
    """Four sites, four paths: a ring through the two hubs and the two corridor cities.

    Five pairs were joined while the fiber was chosen one pair at a time. Choosing it whole
    reaches the same protection over four paths, because b and c reach each other round the
    ring rather than over fiber of their own.
    """
    assert len(_MESH) == 4


def test_the_synthesis_orders_the_fewest_fiber_miles_its_requirements_allow() -> None:
    """Sixteen hundred miles: d's four hundred each way, and a's two ways out at eight hundred.

    d has exactly two fiber directions and needs both, which is eight hundred miles nothing
    can avoid. a then needs two ways out that no one city takes together, and the shortest
    pair it has is h2 to c at three hundred and h1 to b at five hundred. Everything else falls out
    of those: b and c each already hold a hub path and a corridor path to d.
    """
    assert sum(use.distance_miles for use in _MESH) == 1600.0


def test_every_site_still_holds_the_paths_its_tenant_asked_for() -> None:
    """b rides h1 to a and reaches d over its own corridor, which is two ways out."""
    assert ARTIFACTS.validation["backbone_mesh_independence_deficient"] == []


def test_the_fiber_survives_the_loss_of_any_one_city() -> None:
    """No city is left carrying the whole network: the eight segments close into one ring."""
    assert ARTIFACTS.validation["biconnected_no_articulation_points"]


def test_no_path_the_synthesis_holds_could_be_taken_back_out() -> None:
    """Each of the four paths is the second way out of one of the four sites."""
    assert _needed(_MESH, ARTIFACTS.synthesis.backbone_ids, _ASKED_FOR) == _MESH
