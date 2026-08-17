"""Integration test: how many circuits a whole synthesis buys between one pair of sites.

Two sites that are joined are joined once. A second route between the same two sites is a
second circuit somebody orders every month, and it buys nothing the first did not: what
makes a site's ways out independent is that they end at different peers. Only a tenant whose
config leaves its sites no other peer to reach -- a backbone capped at two seats -- can
answer the paths it asked for over one pair, and that case has its own file beside this one.

The shape that overbuilds a pair cannot be made from a clique or a ring, which is why the
tier missed it. It needs the two ends of a pair to prove different fiber to each other, and
they do that when the cheapest way out of one site is spoken for by another of its peers.
Here a, b and c reach each other over three shared hub cities priced so that a is cheap
through h2, b is cheap through h1 and c is cheap through both: a's proved routes are h1 to b
and h2 to c, b's are h1 to a and h3 to c, and c's are h2 to a and h1 to b. So b and c each
proved their own way to the other, five miles through h3 and two through h1, and the design
drew both of them until this was fixed (GitHub issue #59).

The fourth site d is here because dropping a route costs the site that proved it. b's routes
to a and c both ride h1 once the pair is drawn once, so d, joined to b and to c over private
fiber of its own, is what leaves b two ways out that no one city takes together. That is the
network the fix argues for: the money that was buying b a second circuit to c buys a circuit
to a site b did not reach at all.

The hub and corridor cities are not data-center cities, so none of them can take a backbone
seat and the backbone stays the four sites the case is about.
"""

from __future__ import annotations

import fixtures
from synthesizer.input_graph import edge_key
from synthesizer.model import DesignParams, Tuning

_SITES = ("a", "b", "c", "d")
_ASKED_FOR = 2
# Three hub cities every site reaches, priced so the two ends of b-c disagree, and two
# private corridors joining d to b and to c.
_SPANS = {
    ("a", "h1"): 400.0, ("a", "h2"): 100.0, ("a", "h3"): 800.0,
    ("b", "h1"): 100.0, ("b", "h2"): 800.0, ("b", "h3"): 200.0,
    ("c", "h1"): 100.0, ("c", "h2"): 200.0, ("c", "h3"): 300.0,
    ("b", "d1"): 100.0, ("d1", "d"): 300.0,
    ("c", "d2"): 100.0, ("d2", "d"): 300.0,
}
_CITIES = ("a", "b", "c", "d", "h1", "h2", "h3", "d1", "d2")
ARTIFACTS = fixtures.run_design(
    [
        fixtures.carrier_pop(city, 38.0, -115.0 + 2.0 * index)
        for index, city in enumerate(_CITIES)
    ],
    fixtures.physical_edges_from(_SPANS),
    DesignParams(
        min_backbone_count=len(_SITES),
        max_backbone_count=len(_SITES),
        forced_backbone_names=_SITES,
        datacenter_cities=frozenset((site, "XX") for site in _SITES),
        promote_high_degree_convergences=False,
        tuning=Tuning(backbone_number_of_diverse_paths=_ASKED_FOR),
    ),
)
_MESH = [use for use in ARTIFACTS.design.path_uses if use.purpose == "backbone_mesh"]


def _routes_per_pair() -> dict[tuple[str, str], int]:
    """How many routes the finished design drew between each pair of backbone sites.

    Counted off the routed paths rather than through
    ``synthesizer.validation.backbone_mesh_pairs``, which answers with a set: a pair drawn
    twice collapses into the one member it is, so the count of pairs reads the same whether
    the design bought one circuit or two.
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
    """b and c proved different fiber to each other, and one circuit is what is built."""
    assert max(_routes_per_pair().values()) == 1


def test_the_pair_whose_ends_disagreed_takes_the_shorter_of_the_two_routes() -> None:
    """Two hundred miles through h1 rather than five hundred through h3."""
    drawn = [use for use in _MESH if edge_key(use.source, use.target) == edge_key("b", "c")]
    assert drawn[0].path == ("b", "h1", "c")


def test_every_pair_the_sites_reached_for_is_still_joined() -> None:
    """Drawing a pair once is not drawing it none: the five pairs the mesh picked are wired."""
    assert len(_routes_per_pair()) == 5


def test_every_site_still_holds_the_paths_its_tenant_asked_for() -> None:
    """b rides h1 for two of its three links and reaches d clear of it, which is two ways out."""
    assert ARTIFACTS.validation["backbone_mesh_independence_deficient"] == []


def test_the_fiber_survives_the_loss_of_any_one_city() -> None:
    """No city is left carrying the whole network, so the repair pass adds no detour."""
    assert ARTIFACTS.validation["biconnected_no_articulation_points"]
