from __future__ import annotations

import fixtures
from synthesizer.backbone import _needed
from synthesizer.input_graph import link_key

_ASKED_FOR = 2
ARTIFACTS = fixtures.shared_hub_peer_artifacts()
_MESH = fixtures.mesh_paths(ARTIFACTS)


def _paths_per_pair() -> dict[tuple[str, str], int]:
    drawn: dict[tuple[str, str], int] = {}
    for use in _MESH:
        pair = link_key(use.source, use.target)
        drawn[pair] = drawn.get(pair, 0) + 1
    return drawn


def test_the_backbone_is_the_four_sites() -> None:
    assert sorted(ARTIFACTS.synthesis.backbone_ids) == ["a", "b", "c", "d"]


def test_no_pair_of_sites_is_joined_more_than_once() -> None:
    assert max(_paths_per_pair().values()) == 1


def test_the_synthesis_joins_each_site_to_the_two_peers_it_reaches() -> None:
    assert len(_MESH) == 4


def test_the_synthesis_orders_the_fewest_fiber_miles_its_requirements_allow() -> None:
    assert sum(use.distance_miles for use in _MESH) == 1600.0


def test_every_site_still_holds_the_paths_its_tenant_asked_for() -> None:
    assert ARTIFACTS.validation["backbone_mesh_independence_deficient"] == []


def test_the_fiber_survives_the_loss_of_any_one_city() -> None:
    assert ARTIFACTS.validation["biconnected_no_articulation_points"]


def test_no_path_the_synthesis_holds_could_be_taken_back_out() -> None:
    assert _needed(_MESH, ARTIFACTS.synthesis.backbone_ids, _ASKED_FOR) == _MESH
