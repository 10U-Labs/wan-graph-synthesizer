"""Integration test: what a whole synthesis builds when the backbone holds only two sites.

A backbone of two sites is the case where a site cannot answer its tenant by reaching more
peers, because there is only one peer to reach. It has to double up on that peer instead,
and every step from the path proof to the validation report has to agree that two paths
over the one pair are the two paths asked for.

No one unit can show that. The proof, the selection, the routing, the resilience repair and
the report each looked right on their own while the synthesis they made together carried five
paths between Ashburn, VA and Salt Lake City, UT against a tenant asking for one path and
was reported as meeting it (GitHub issue #58). So the whole pipeline is run here and the
finished synthesis is asserted.

The fiber joins the two sites three ways that share no city, at 200, 400 and 1,800 miles.
Three is more than the tenant asked for, which is what makes the count worth asserting: a
synthesis that treats the number as a floor takes all three, and one that stops at a single
path and repairs it afterwards takes two paths plus a detour per single point of failure city. The
1,800-mile way round is there so that which two were taken can be asserted as well as how
many.

The transit cities are barred from the backbone, so neither can take a seat and the
backbone stays the two sites the case is about.
"""

from __future__ import annotations

import fixtures
from synthesizer.model import LINK_FOR_TARGET

_SITES = ("a", "b")
_ASKED_FOR = 2
# Three disjoint ways from a to b, priced so the third is plainly the one to leave out.
_SEGMENTS = {
    ("a", "north"): 100.0, ("north", "b"): 100.0,
    ("a", "south"): 200.0, ("south", "b"): 200.0,
    ("a", "long"): 900.0, ("long", "b"): 900.0,
}
_TRANSIT = ("north", "south", "long")
ARTIFACTS = fixtures.synthesis_over_segments(_SITES, _SEGMENTS, _ASKED_FOR, _TRANSIT)
_MESH = fixtures.mesh_paths(ARTIFACTS)


def test_the_backbone_is_the_two_sites() -> None:
    """The transit cities are barred from the backbone, so they take no seat."""
    assert sorted(ARTIFACTS.synthesis.backbone_ids) == ["a", "b"]


def test_the_pair_is_drawn_with_the_paths_the_tenant_asked_for() -> None:
    """Two asked for over fiber offering three, so two paths are built and no more."""
    assert len(_MESH) == _ASKED_FOR


def test_the_paths_drawn_are_the_shortest_of_the_ones_open_to_it() -> None:
    """The 1,800-mile way round is the one left unbuilt, not either of the shorter two."""
    assert sorted(use.path[1] for use in _MESH) == ["north", "south"]


def test_the_two_paths_share_no_city_but_the_two_sites() -> None:
    """Sharing a transit city would make them one path that a single city's loss takes."""
    transit = [city for use in _MESH for city in use.path[1:-1]]
    assert sorted(transit) == sorted(set(transit))


def test_both_paths_are_ones_the_two_sites_reached_for_themselves() -> None:
    """Two paths over one pair is what a two-site backbone asking for two paths buys.

    There was a fifth reason a path could carry until GitHub issue #60 -- a detour added
    afterwards to keep a city off the only path -- and a synthesis that drew one path and then
    repaired it would have shown up here as that reason rather than as the tenant's own
    number. The fiber is chosen for the whole synthesis at once now, so the two paths are the
    two the sites were bought and neither is a repair of the other.
    """
    assert [use.reason for use in _MESH] == [LINK_FOR_TARGET, LINK_FOR_TARGET]


def test_each_site_is_credited_with_the_paths_it_holds() -> None:
    """Two paths to the one peer are counted as the two ways out they are, not as one."""
    assert ARTIFACTS.validation["backbone_mesh_independence_deficient"] == []
