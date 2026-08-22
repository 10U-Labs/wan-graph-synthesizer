from __future__ import annotations

from itertools import combinations
from typing import cast

import fixtures
from synthesizer.backbone import _needed
from synthesizer.model import LINK_FOR_TARGET
from synthesizer.validation import backbone_mesh_pairs

_SITES = tuple(f"S{index}" for index in range(6))
_ASKED_FOR = 2
_FULL_MESH = len(_SITES) * (len(_SITES) - 1) // 2
_SEGMENTS = {
    (_SITES[left], _SITES[right]): 100.0 * (right - left)
    for left, right in combinations(range(len(_SITES)), 2)
}
ARTIFACTS = fixtures.synthesis_over_segments(
    _SITES, _SEGMENTS, _ASKED_FOR, min_backbone_count=2
)
_MESH = fixtures.mesh_paths(ARTIFACTS)


def test_the_synthesis_does_not_wire_the_full_mesh() -> None:
    assert len(backbone_mesh_pairs(ARTIFACTS.synthesis)) < _FULL_MESH


def test_every_site_still_holds_the_paths_its_tenant_asked_for() -> None:
    assert ARTIFACTS.validation["backbone_mesh_independence_deficient"] == []


def test_every_path_in_the_synthesis_answers_a_sites_own_requirement() -> None:
    assert {use.reason for use in _MESH} == {LINK_FOR_TARGET}


def test_no_path_in_the_synthesis_could_be_taken_back_out() -> None:
    assert _needed(_MESH, ARTIFACTS.synthesis.backbone_ids, _ASKED_FOR) == _MESH


def test_no_site_is_reported_above_the_number_with_nothing_to_blame() -> None:
    above = ARTIFACTS.validation["backbone_diverse_paths_above_target"]
    assert all(entry["unrequested_links"] for entry in above)


def test_every_path_past_the_number_names_the_peer_that_reached_for_it() -> None:
    above = ARTIFACTS.validation["backbone_diverse_paths_above_target"]
    assert {
        str(link["reason"])
        for entry in above
        for link in cast(list[dict[str, object]], entry["unrequested_links"])
    } <= {"peer_target"}
