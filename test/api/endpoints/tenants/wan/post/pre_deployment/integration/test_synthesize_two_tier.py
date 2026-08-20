"""Integration test: the synthesizer over the synthetic ring graph.

A six-PoP ring is 2-connected, so it meshes into a resilient backbone; a degree-one
spur confirms such PoPs are never backbone nodes. The ring carries carrier PoPs only --
in the two-tier model demand homes to the backbone over the physical graph, so demand
homing is exercised at the unit level (see ``test_synthesize.py``).
"""

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
    is_carrier_pop,
)
from synthesizer.synthesize import convergence_promotion_ids
from synthesizer.validation import backbone_mesh_pairs, diverse_path_count

ARTIFACTS = fixtures.ring_artifacts()
FORCED = fixtures.forced_backbone_artifacts("P3")
FORCED_ROADM = fixtures.forced_roadm_backbone_artifacts("P3")
PROHIBITED = fixtures.prohibited_backbone_artifacts("P4")

# A forced backbone-backbone link over the ring, resolved through the operator-pin path
# so the asserted link reflects a genuinely honored request. All six ring PoPs are
# seated so the diverse path count binds: P0 and P3 sit opposite each other, three hops apart,
# and are each other's farthest peer, so a nearest-neighbour mesh never picks the pair
# and the ring is already bridgeless without it. The link can only be the pin.
#
# The degree is two because each ring PoP has two fiber directions, so two links is the
# most any of them can hold independently and a three-link synthesis over this graph is
# refused (see ``test_the_ring_cannot_meet_a_degree_its_fiber_cannot_carry``).
_RING_BACKBONE = ("P0", "P1", "P2", "P3", "P4", "P5")
_MESHED_RING = SynthesisParams(
    min_backbone_count=2,
    forced_backbone_names=_RING_BACKBONE,
    datacenter_cities=fixtures.ring_datacenter_cities(),
    tuning=Tuning(backbone_number_of_diverse_paths=2),
)
FORCED_BACKBONE_LINK = fixtures.forced_link_artifacts(
    _MESHED_RING, OperatorLinks(backbone=(NamedLink("P0", "P3"),))
)
UNFORCED_RING = fixtures.forced_link_artifacts(_MESHED_RING, OperatorLinks())

# The same ring plus one demand site sitting on P0, so P0 is its nearest node and the
# opposite P3 is its farthest. With two homes per site, distance alone never reaches P3,
# so a home there can only be the operator's pin -- carried from the `forced-homes` list
# through `apply_role_overrides` and into the synthesis's access links.
_DEMAND_RING = fixtures.ring_inputs_with_demand("S1", "P0")
FORCED_HOME = fixtures.forced_link_artifacts(
    _MESHED_RING, OperatorLinks(access=(NamedLink("S1", "P3"),)), _DEMAND_RING
)
UNFORCED_HOME = fixtures.forced_link_artifacts(_MESHED_RING, OperatorLinks(), _DEMAND_RING)


def _homes_of(artifacts: SynthesisArtifacts, access_id: str) -> set[str]:
    """The backbone nodes a demand site homes to in a finished synthesis."""
    return {
        link.target for link in artifacts.synthesis.access_paths if link.source == access_id
    }


def _peers_of(artifacts: SynthesisArtifacts, node: str) -> set[str]:
    """Every backbone node sharing a finished mesh link with ``node``."""
    return {
        end
        for pair in backbone_mesh_pairs(artifacts.synthesis)
        if node in pair
        for end in pair
        if end != node
    }


def test_the_opposite_pair_is_never_meshed_on_its_own() -> None:
    """Without the pin the opposite pair is unmeshed, so the forced case cannot pass by luck."""
    assert link_key("P0", "P3") not in backbone_mesh_pairs(UNFORCED_RING.synthesis)


def test_a_forced_backbone_path_appears_in_the_mesh() -> None:
    """A forced backbone-backbone path is present in the drawn backbone mesh."""
    assert link_key("P0", "P3") in backbone_mesh_pairs(FORCED_BACKBONE_LINK.synthesis)


def test_the_opposite_backbone_is_never_a_home_on_its_own() -> None:
    """Without the pin the farthest node is no home, so the forced case cannot pass by luck."""
    assert "P3" not in _homes_of(UNFORCED_HOME, "S1")


def test_a_forced_home_is_honored_in_the_finished_synthesis() -> None:
    """A forced home reaches the synthesis's access links, over the PoP the site sits on."""
    assert "P3" in _homes_of(FORCED_HOME, "S1")


def test_forced_pop_is_placed_in_the_backbone() -> None:
    """A PoP named on the force-backbone list is honored as a backbone node."""
    assert "P3" in FORCED.synthesis.backbone_ids


def test_forced_roadm_is_seated_in_the_backbone() -> None:
    """A pinned ROADM is honored as a backbone node.

    The force is what seats it, whatever kind the point is. The operator's own pins are
    all forced PoPs -- `Great Falls, MT` and `Minot, ND` under `backbone.forced.nodes` in
    `etc/daf.yml` are carrier rows like any other -- so the ROADM here is made by
    `ring_inputs_with_roadm`, which recasts one site of the in-memory ring.
    """
    assert "P3" in FORCED_ROADM.synthesis.backbone_ids


def test_prohibited_pop_is_kept_off_the_backbone() -> None:
    """A prohibited PoP never reaches the backbone."""
    assert "P4" not in PROHIBITED.synthesis.backbone_ids


def test_honors_the_backbone_count_minimum() -> None:
    """The synthesis has at least the minimum number of backbone nodes."""
    assert len(ARTIFACTS.synthesis.backbone_ids) >= 2


def test_degree_one_spur_is_not_a_backbone_node() -> None:
    """A degree-one spur is never selected as a backbone node."""
    assert "P6" not in ARTIFACTS.synthesis.backbone_ids


def test_backbone_meets_the_mesh_link_target() -> None:
    """Every backbone node wires to its configured number of nearest peers on the mesh."""
    assert ARTIFACTS.validation["backbone_meets_mesh_link_target"] is True


def test_synthesis_is_connected() -> None:
    """The whole ring synthesis validates as a single connected component."""
    assert ARTIFACTS.validation["connected"] is True


def test_backbone_survives_any_single_city() -> None:
    """No one city is a single point of failure on the ring backbone (biconnected)."""
    assert ARTIFACTS.validation["backbone_mesh_survives_any_one_site_loss"] is True


def test_every_meshed_ring_node_holds_its_links_independently() -> None:
    """Each seated ring PoP holds two mesh links no single city's loss can both take."""
    assert UNFORCED_RING.validation["backbone_meets_independent_mesh_link_target"] is True


_RING_AT_THREE = fixtures.forced_link_artifacts(
    replace(_MESHED_RING, tuning=Tuning(backbone_number_of_diverse_paths=3)), OperatorLinks()
)


def test_a_degree_the_ring_cannot_carry_is_lowered_rather_than_refused() -> None:
    """Every ring PoP has two ways out, so three is a number no exemption need excuse.

    A ring node's ceiling is two, so two is what it is asked for and the synthesis the
    operator wanted is built. The degree the tool cannot honour is the ground's answer,
    not a defect: refusing here used to make the operator name each node by hand.
    """
    assert _RING_AT_THREE.validation["backbone_meets_independent_mesh_link_target"] is True


def test_the_ring_reports_every_node_whose_target_it_lowered() -> None:
    """All six ring PoPs are held to two, and the report says so of each one."""
    lowered = _RING_AT_THREE.validation["backbone_diverse_paths_ceiling_limited"]
    assert [entry["id"] for entry in lowered] == list(_RING_BACKBONE)


# The ring with four chords, so P0 through P4 each have a third fiber direction and P5
# keeps only its two ring neighbours. At three diverse paths P5 is the one node the
# fiber cannot carry: the spur an operator exempts, with every other node meeting the
# degree, which is what makes the exemption's effect legible here.
_CHORDED_PAIRS = {
    ("P0", "P1"): 100.0, ("P1", "P2"): 100.0, ("P2", "P3"): 100.0,
    ("P3", "P4"): 100.0, ("P4", "P5"): 100.0, ("P5", "P0"): 100.0,
    ("P0", "P2"): 100.0, ("P0", "P3"): 100.0, ("P1", "P3"): 100.0, ("P2", "P4"): 100.0,
}
_CHORDED_BACKBONE = ("P0", "P1", "P2", "P3", "P4", "P5")


def _chorded_synthesis(exempt: tuple[str, ...] = ()) -> SynthesisArtifacts:
    """Synthesize the chorded ring at three diverse paths, exempting the named nodes."""
    sites = [
        fixtures.carrier_pop(name, *fixtures.RING_COORDS[name]) for name in _CHORDED_BACKBONE
    ]
    params = SynthesisParams(
        min_backbone_count=2,
        forced_backbone_names=_CHORDED_BACKBONE,
        degree_exempt_backbone_names=exempt,
        datacenter_cities=fixtures.ring_datacenter_cities(),
        tuning=Tuning(backbone_number_of_diverse_paths=3),
    )
    return run_synthesis(sites, fixtures.fiber_segments_from(_CHORDED_PAIRS), params)


EXEMPT_SPUR = _chorded_synthesis(("P5",))
CHORDED = _chorded_synthesis()


def test_the_chorded_ring_is_no_longer_refused_at_its_one_spur() -> None:
    """P5's ceiling is two, so nobody has to exempt it for the synthesis to be built.

    This is the case the exemption list existed for and no longer has to cover: the
    shortfall was the ground's all along, and the tool can see that for itself.
    """
    assert CHORDED.validation["backbone_meets_independent_mesh_link_target"] is True


def test_the_chorded_ring_names_the_spur_whose_target_it_lowered() -> None:
    """The published report says P5 was held to two, so the reduction is read not inferred."""
    assert CHORDED.validation["backbone_diverse_paths_ceiling_limited"] == [
        {"id": "P5", "name": "P5", "ceiling": 2}
    ]


def test_a_chorded_node_ends_above_the_number_because_a_peer_asked() -> None:
    """Some node holds more ways out than the three asked of it, and no node asked for more.

    A site takes the number its tenant bought and no more. Six nodes owing three ways out
    apiece, and one of them held to two by its own fiber, come to seventeen ends; the paths
    that carry them have thirty-four ends between them, so at least one node is holding a
    path some peer reached for. Which node that is depends on which of the ten segments the
    fiber choice leaves unbought, and there is nothing in the tenant's config that decides
    it -- so what is worth pinning is that it happens, not who it happens to.
    """
    assert max(
        diverse_path_count(CHORDED.synthesis.path_uses, node) for node in _CHORDED_BACKBONE
    ) > 3


def test_the_chorded_ring_names_the_nodes_holding_more_than_was_asked() -> None:
    """Every node above three links is named, so an operator reads the surplus not the count."""
    above = CHORDED.validation["backbone_diverse_paths_above_target"]
    assert above != []


def test_every_link_past_the_number_is_attributed_to_a_peer() -> None:
    """No node is over on the tool's own account: every extra link names the peer.

    This is the guarantee the exact target buys. A link above the number has to trace back
    to somebody's requirement, and on this graph every one of them traces to a peer that
    needed the node to reach its own.
    """
    above = CHORDED.validation["backbone_diverse_paths_above_target"]
    assert {
        str(link["reason"])
        for entry in above
        for link in cast(list[dict[str, object]], entry["unrequested_links"])
    } == {"peer_target"}


def test_no_chorded_node_finishes_below_what_its_own_fiber_allows() -> None:
    """Every node ends at the smaller of the tenant degree and its ceiling, none under it.

    This is the guarantee the whole pipeline owes and the one that decides whether a synthesis
    is built at all. A node under that number is not a fact about the ground -- the ceiling
    has already given the ground its say -- so it is the tool falling short of what it can
    see is possible, and it refuses the synthesis over it. The mesh is built along the very
    paths the ceiling proved exist, so a node holds as many independent links as its own
    fiber was already known to carry, rather than as many as choosing peers by distance
    happened to leave it with.
    """
    ceilings = CHORDED.validation["backbone_diverse_paths_ceiling_limited"]
    capped = {str(entry["id"]): int(str(entry["ceiling"])) for entry in ceilings}
    assert [
        node
        for node in _CHORDED_BACKBONE
        if diverse_path_count(CHORDED.synthesis.path_uses, node) < min(3, capped.get(node, 3))
    ] == []


def test_exempting_the_spur_lets_the_synthesis_finalize() -> None:
    """With P5 exempt the mesh target is met, so the synthesis the operator wanted is built."""
    assert EXEMPT_SPUR.validation["backbone_meets_independent_mesh_link_target"] is True


def test_the_exempt_spur_is_named_in_the_finished_report() -> None:
    """The published report says which node the degree was not asked of."""
    assert EXEMPT_SPUR.validation["backbone_degree_exempt"] == [{"id": "P5", "name": "P5"}]


def test_the_exempt_spur_picks_its_own_two_fiber_directions() -> None:
    """Exempting P5 relieves it of the degree without stopping it choosing peers.

    P0 and P4 are the two cities P5 has fiber to, and both are links P5 chose itself
    rather than links some farther node reached for.
    """
    assert {"P0", "P4"} <= _peers_of(EXEMPT_SPUR, "P5")


def _forced_off_net_artifacts() -> SynthesisArtifacts:
    """Synthesize over the ring with an off-net site forced as a backbone node."""
    site, params = fixtures.forced_off_net_case()
    return run_synthesis(
        fixtures.ring_sites(), fixtures.ring_fiber_segments(), params, off_net_sites=[site]
    )


def test_forced_off_net_site_is_seated_in_the_backbone() -> None:
    """A forced off-net site's local-fiber twin lands in the backbone."""
    synthesis = _forced_off_net_artifacts().synthesis
    assert any(node.startswith("offnet_") for node in synthesis.backbone_ids)


def test_off_net_synthesis_validates_connected() -> None:
    """A synthesis with an off-net backbone twin validates as a connected whole."""
    artifacts = _forced_off_net_artifacts()
    assert artifacts.validation["connected"] is True


CONVERGENCE_HUB = fixtures.convergence_hub_artifacts()
NON_DATACENTER_HUB = fixtures.convergence_hub_artifacts(promote_hub=False)


def test_promoted_convergence_hub_is_seated_in_the_backbone() -> None:
    """The data-center transit hub carrying >= 3 lines is promoted into the backbone."""
    assert "hub_dc" in CONVERGENCE_HUB.synthesis.backbone_ids


def test_promoted_convergence_synthesis_validates_connected() -> None:
    """The synthesis with the promoted hub still validates end-to-end as connected."""
    assert CONVERGENCE_HUB.validation["connected"] is True


def test_convergence_promotion_reaches_a_fixpoint() -> None:
    """The returned synthesis is stable: a further convergence pass promotes nothing."""
    carrier_pops = [v for v in CONVERGENCE_HUB.sites if is_carrier_pop(v)]
    cities = frozenset(
        (pop.info.municipality, pop.info.state) for pop in carrier_pops
    )
    assert convergence_promotion_ids(CONVERGENCE_HUB.synthesis, carrier_pops, cities) == set()


def test_non_data_center_convergence_hub_is_not_promoted() -> None:
    """The same >= 3-line crossing with no data center is never promoted to backbone."""
    assert "hub_dc" not in NON_DATACENTER_HUB.synthesis.backbone_ids


def test_non_data_center_convergence_hub_stays_transit() -> None:
    """The unpromoted >= 3-line crossing remains a transit node in the synthesis."""
    assert "hub_dc" in NON_DATACENTER_HUB.synthesis.transit_ids


def _open_gate_artifacts() -> SynthesisArtifacts:
    """Synthesize over the ring with the gate open (datacenter_cities=None) and P3 forced.

    ``datacenter_cities=None`` is the operator's free-for-all: no data-center set is
    supplied at all, so a forced PoP would be rejected under the default gate yet is
    accepted here. Drives the full deployed pipeline (dual-home -> overrides ->
    synthesize -> finalize) via ``run_synthesis``.
    """
    params = SynthesisParams(
        min_backbone_count=2, forced_backbone_names=("P3",), datacenter_cities=None
    )
    return run_synthesis(fixtures.ring_sites(), fixtures.ring_fiber_segments(), params)


def test_open_gate_seats_a_forced_non_data_center_backbone() -> None:
    """With the gate open, a forced PoP at no data-center city is seated in the backbone."""
    assert "P3" in _open_gate_artifacts().synthesis.backbone_ids


def test_open_gate_synthesis_validates_connected() -> None:
    """The open-gate synthesis validates end-to-end as a single connected component."""
    assert _open_gate_artifacts().validation["connected"] is True
