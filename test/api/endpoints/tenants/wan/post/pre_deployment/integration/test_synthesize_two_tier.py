from __future__ import annotations

from dataclasses import replace
from typing import cast

import fixtures
from fixtures import run_synthesis
from synthesizer.input_graph import link_key
from synthesizer.model import (
    SynthesisArtifacts,
    SynthesisParams,
    NamedLink,
    OperatorLinks,
    Tuning,
)
from synthesizer.synthesize import convergence_promotion_ids
from synthesizer.validation import backbone_mesh_pairs, diverse_path_count

ARTIFACTS = fixtures.ring_artifacts()
FORCED = fixtures.forced_backbone_artifacts("P3")
FORCED_ROADM = fixtures.forced_roadm_backbone_artifacts("P3")
PROHIBITED = fixtures.prohibited_backbone_artifacts("P4")

_RING_BACKBONE = ("P0", "P1", "P2", "P3", "P4", "P5")
_MESHED_RING = SynthesisParams(
    min_backbone_count=2,
    forced_backbone_names=_RING_BACKBONE,
    tuning=Tuning(backbone_number_of_diverse_paths=2),
)
FORCED_BACKBONE_LINK = fixtures.forced_link_artifacts(
    _MESHED_RING, OperatorLinks(backbone=(NamedLink("P0", "P3"),))
)
UNFORCED_RING = fixtures.forced_link_artifacts(_MESHED_RING, OperatorLinks())

_DEMAND_RING = fixtures.ring_inputs_with_demand("S1", "P0")
FORCED_HOME = fixtures.forced_link_artifacts(
    _MESHED_RING, OperatorLinks(access=(NamedLink("S1", "P3"),)), _DEMAND_RING
)
UNFORCED_HOME = fixtures.forced_link_artifacts(_MESHED_RING, OperatorLinks(), _DEMAND_RING)


def _homes_of(artifacts: SynthesisArtifacts, access_id: str) -> set[str]:
    return {
        link.target for link in artifacts.synthesis.access_paths if link.source == access_id
    }


def _peers_of(artifacts: SynthesisArtifacts, node: str) -> set[str]:
    return {
        end
        for pair in backbone_mesh_pairs(artifacts.synthesis)
        if node in pair
        for end in pair
        if end != node
    }


def test_the_opposite_pair_is_never_meshed_on_its_own() -> None:
    assert link_key("P0", "P3") not in backbone_mesh_pairs(UNFORCED_RING.synthesis)


def test_a_forced_backbone_path_appears_in_the_mesh() -> None:
    assert link_key("P0", "P3") in backbone_mesh_pairs(FORCED_BACKBONE_LINK.synthesis)


def test_the_opposite_backbone_is_never_a_home_on_its_own() -> None:
    assert "P3" not in _homes_of(UNFORCED_HOME, "S1")


def test_a_forced_home_is_honored_in_the_finished_synthesis() -> None:
    assert "P3" in _homes_of(FORCED_HOME, "S1")


def test_forced_pop_is_placed_in_the_backbone() -> None:
    assert "P3" in FORCED.synthesis.backbone_ids


def test_forced_roadm_is_seated_in_the_backbone() -> None:
    assert "P3" in FORCED_ROADM.synthesis.backbone_ids


def test_prohibited_pop_is_kept_off_the_backbone() -> None:
    assert "P4" not in PROHIBITED.synthesis.backbone_ids


def test_honors_the_backbone_count_minimum() -> None:
    assert len(ARTIFACTS.synthesis.backbone_ids) >= 2


def test_degree_one_spur_is_not_a_backbone_node() -> None:
    assert "P6" not in ARTIFACTS.synthesis.backbone_ids


def test_backbone_meets_the_mesh_link_target() -> None:
    assert ARTIFACTS.validation["backbone_meets_mesh_link_target"] is True


def test_synthesis_is_connected() -> None:
    assert ARTIFACTS.validation["connected"] is True


def test_backbone_survives_any_single_city() -> None:
    assert ARTIFACTS.validation["backbone_mesh_survives_any_one_site_loss"] is True


def test_every_meshed_ring_node_holds_its_links_independently() -> None:
    assert UNFORCED_RING.validation["backbone_meets_independent_mesh_link_target"] is True


_RING_AT_THREE = fixtures.forced_link_artifacts(
    replace(_MESHED_RING, tuning=Tuning(backbone_number_of_diverse_paths=3)), OperatorLinks()
)


def test_a_degree_the_ring_cannot_carry_is_lowered_rather_than_refused() -> None:
    assert _RING_AT_THREE.validation["backbone_meets_independent_mesh_link_target"] is True


def test_the_ring_reports_every_node_whose_target_it_lowered() -> None:
    lowered = _RING_AT_THREE.validation["backbone_diverse_paths_ceiling_limited"]
    assert [entry["id"] for entry in lowered] == list(_RING_BACKBONE)


_CHORDED_PAIRS = {
    ("P0", "P1"): 100.0, ("P1", "P2"): 100.0, ("P2", "P3"): 100.0,
    ("P3", "P4"): 100.0, ("P4", "P5"): 100.0, ("P5", "P0"): 100.0,
    ("P0", "P2"): 100.0, ("P0", "P3"): 100.0, ("P1", "P3"): 100.0, ("P2", "P4"): 100.0,
}
_CHORDED_BACKBONE = ("P0", "P1", "P2", "P3", "P4", "P5")


def _chorded_synthesis(exempt: tuple[str, ...] = ()) -> SynthesisArtifacts:
    sites = [
        fixtures.carrier_pop(name, *fixtures.RING_COORDS[name]) for name in _CHORDED_BACKBONE
    ]
    params = SynthesisParams(
        min_backbone_count=2,
        forced_backbone_names=_CHORDED_BACKBONE,
        degree_exempt_backbone_names=exempt,
        tuning=Tuning(backbone_number_of_diverse_paths=3),
    )
    return run_synthesis(sites, fixtures.fiber_segments_from(_CHORDED_PAIRS), params)


EXEMPT_SPUR = _chorded_synthesis(("P5",))
CHORDED = _chorded_synthesis()


def test_the_chorded_ring_is_no_longer_refused_at_its_one_spur() -> None:
    assert CHORDED.validation["backbone_meets_independent_mesh_link_target"] is True


def test_the_chorded_ring_names_the_spur_whose_target_it_lowered() -> None:
    assert CHORDED.validation["backbone_diverse_paths_ceiling_limited"] == [
        {"id": "P5", "name": "P5", "ceiling": 2}
    ]


def test_a_chorded_node_ends_above_the_number_because_a_peer_asked() -> None:
    assert max(
        diverse_path_count(CHORDED.synthesis.path_uses, node) for node in _CHORDED_BACKBONE
    ) > 3


def test_the_chorded_ring_names_the_nodes_holding_more_than_was_asked() -> None:
    above = CHORDED.validation["backbone_diverse_paths_above_target"]
    assert above != []


def test_every_link_past_the_number_is_attributed_to_a_peer() -> None:
    above = CHORDED.validation["backbone_diverse_paths_above_target"]
    assert {
        str(link["reason"])
        for entry in above
        for link in cast(list[dict[str, object]], entry["unrequested_links"])
    } == {"peer_target"}


def test_no_chorded_node_finishes_below_what_its_own_fiber_allows() -> None:
    ceilings = CHORDED.validation["backbone_diverse_paths_ceiling_limited"]
    capped = {str(entry["id"]): int(str(entry["ceiling"])) for entry in ceilings}
    assert [
        node
        for node in _CHORDED_BACKBONE
        if diverse_path_count(CHORDED.synthesis.path_uses, node) < min(3, capped.get(node, 3))
    ] == []


def test_exempting_the_spur_lets_the_synthesis_finalize() -> None:
    assert EXEMPT_SPUR.validation["backbone_meets_independent_mesh_link_target"] is True


def test_the_exempt_spur_is_named_in_the_finished_report() -> None:
    assert EXEMPT_SPUR.validation["backbone_degree_exempt"] == [{"id": "P5", "name": "P5"}]


def test_the_exempt_spur_picks_its_own_two_fiber_directions() -> None:
    assert {"P0", "P4"} <= _peers_of(EXEMPT_SPUR, "P5")


def _forced_off_net_artifacts() -> SynthesisArtifacts:
    site, params = fixtures.forced_off_net_case()
    return run_synthesis(
        fixtures.ring_sites(), fixtures.ring_fiber_segments(), params, off_net_sites=[site]
    )


def test_forced_off_net_site_is_seated_in_the_backbone() -> None:
    synthesis = _forced_off_net_artifacts().synthesis
    assert any(node.startswith("offnet_") for node in synthesis.backbone_ids)


def test_off_net_synthesis_validates_connected() -> None:
    artifacts = _forced_off_net_artifacts()
    assert artifacts.validation["connected"] is True


CONVERGENCE_HUB = fixtures.convergence_hub_artifacts()


def test_promoted_convergence_hub_is_seated_in_the_backbone() -> None:
    assert "hub_dc" in CONVERGENCE_HUB.synthesis.backbone_ids


def test_promoted_convergence_synthesis_validates_connected() -> None:
    assert CONVERGENCE_HUB.validation["connected"] is True


def test_convergence_promotion_reaches_a_fixpoint() -> None:
    assert convergence_promotion_ids(CONVERGENCE_HUB.synthesis) == set()
