from __future__ import annotations

import fixtures
from synthesizer.model import LINK_FOR_TARGET

_SITES = ("a", "b")
_ASKED_FOR = 2
_SEGMENTS = {
    ("a", "north"): 100.0, ("north", "b"): 100.0,
    ("a", "south"): 200.0, ("south", "b"): 200.0,
    ("a", "long"): 900.0, ("long", "b"): 900.0,
}
_TRANSIT = ("north", "south", "long")
ARTIFACTS = fixtures.synthesis_over_segments(_SITES, _SEGMENTS, _ASKED_FOR, _TRANSIT)
_MESH = fixtures.mesh_paths(ARTIFACTS)


def test_the_backbone_is_the_two_sites() -> None:
    assert sorted(ARTIFACTS.synthesis.backbone_ids) == ["a", "b"]


def test_the_pair_is_drawn_with_the_paths_the_tenant_asked_for() -> None:
    assert len(_MESH) == _ASKED_FOR


def test_the_paths_drawn_are_the_shortest_of_the_ones_open_to_it() -> None:
    assert sorted(use.path[1] for use in _MESH) == ["north", "south"]


def test_the_two_paths_share_no_city_but_the_two_sites() -> None:
    transit = [city for use in _MESH for city in use.path[1:-1]]
    assert sorted(transit) == sorted(set(transit))


def test_both_paths_are_ones_the_two_sites_reached_for_themselves() -> None:
    assert [use.reason for use in _MESH] == [LINK_FOR_TARGET, LINK_FOR_TARGET]


def test_each_site_is_credited_with_the_paths_it_holds() -> None:
    assert ARTIFACTS.validation["backbone_mesh_independence_deficient"] == []
