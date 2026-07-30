"""Integration test: the synthesizer over the synthetic ring graph.

A six-PoP ring is 2-connected, so it meshes into a resilient backbone; a degree-one
spur confirms such PoPs are never backbone nodes. The ring carries carrier PoPs only --
in the two-tier model demand homes to the backbone over the physical graph, so demand
homing is exercised at the unit level (see ``test_synthesize.py``).
"""

from __future__ import annotations

from dataclasses import replace

import fixtures
import pytest
from fixtures import run_design
from synthesizer.input_graph import edge_key
from synthesizer.model import (
    DesignArtifacts,
    DesignParams,
    NamedLink,
    OperatorLinks,
    Tuning,
    is_carrier_pop,
)
from synthesizer.synthesize import convergence_promotion_ids
from synthesizer.validation import backbone_mesh_pairs

ARTIFACTS = fixtures.ring_artifacts()
FORCED = fixtures.forced_backbone_artifacts("P3")
FORCED_ROADM = fixtures.forced_roadm_backbone_artifacts("P3")
PROHIBITED = fixtures.prohibited_backbone_artifacts("P4")

# A forced backbone-backbone link over the ring, resolved through the operator-pin path
# so the asserted edge reflects a genuinely honored request. All six ring PoPs are
# seated so the mesh degree binds: P0 and P3 sit opposite each other, three hops apart,
# and are each other's farthest peer, so a nearest-neighbour mesh never picks the pair
# and the ring is already 2-edge-connected without it. The link can only be the pin.
#
# The degree is two because each ring PoP has two fiber directions, so two links is the
# most any of them can hold independently and a three-link design over this graph is
# refused (see ``test_the_ring_cannot_meet_a_degree_its_fiber_cannot_carry``).
_RING_BACKBONE = ("P0", "P1", "P2", "P3", "P4", "P5")
_MESHED_RING = DesignParams(
    min_backbone_count=2,
    forced_backbone_names=_RING_BACKBONE,
    datacenter_cities=fixtures.ring_datacenter_cities(),
    tuning=Tuning(backbone_mesh_degree=2),
)
FORCED_BACKBONE_LINK = fixtures.forced_link_artifacts(
    _MESHED_RING, OperatorLinks(backbone=(NamedLink("P0", "P3"),))
)
UNFORCED_RING = fixtures.forced_link_artifacts(_MESHED_RING, OperatorLinks())

# The same ring plus one demand vertex sitting on P0, so P0 is its nearest node and the
# opposite P3 is its farthest. With two homes per site, distance alone never reaches P3,
# so a home there can only be the operator's pin -- carried from the `forced-homes` list
# through `apply_role_overrides` and into the design's access edges.
_DEMAND_RING = fixtures.ring_inputs_with_demand("S1", "P0")
FORCED_HOME = fixtures.forced_link_artifacts(
    _MESHED_RING, OperatorLinks(access=(NamedLink("S1", "P3"),)), _DEMAND_RING
)
UNFORCED_HOME = fixtures.forced_link_artifacts(_MESHED_RING, OperatorLinks(), _DEMAND_RING)


def _homes_of(artifacts: DesignArtifacts, access_id: str) -> set[str]:
    """The backbone nodes a demand vertex homes to in a finished design."""
    return {
        edge.target for edge in artifacts.design.access_edges if edge.source == access_id
    }


def test_the_opposite_pair_is_never_meshed_on_its_own() -> None:
    """Without the pin the opposite pair is unmeshed, so the forced case cannot pass by luck."""
    assert edge_key("P0", "P3") not in backbone_mesh_pairs(UNFORCED_RING.design)


def test_forced_backbone_connection_appears_in_the_mesh() -> None:
    """A forced backbone-backbone connection is present in the routed backbone mesh."""
    assert edge_key("P0", "P3") in backbone_mesh_pairs(FORCED_BACKBONE_LINK.design)


def test_the_opposite_backbone_is_never_a_home_on_its_own() -> None:
    """Without the pin the farthest node is no home, so the forced case cannot pass by luck."""
    assert "P3" not in _homes_of(UNFORCED_HOME, "S1")


def test_a_forced_home_is_honored_in_the_finished_design() -> None:
    """A forced home reaches the design's access edges, over the PoP the site sits on."""
    assert "P3" in _homes_of(FORCED_HOME, "S1")


def test_forced_pop_is_placed_in_the_backbone() -> None:
    """A PoP named on the force-backbone list is honored as a backbone node."""
    assert "P3" in FORCED.design.backbone_ids


def test_forced_roadm_is_seated_in_the_backbone() -> None:
    """A pinned ROADM is honored as a backbone node.

    ROADMs are eligible like any other point, and a force always wins regardless; this
    is the mechanism the AFGSC Great Falls and Minot ROADM pins rely on.
    """
    assert "P3" in FORCED_ROADM.design.backbone_ids


def test_prohibited_pop_is_kept_off_the_backbone() -> None:
    """A prohibited PoP never reaches the backbone."""
    assert "P4" not in PROHIBITED.design.backbone_ids


def test_honors_the_backbone_count_minimum() -> None:
    """The design has at least the minimum number of backbone nodes."""
    assert len(ARTIFACTS.design.backbone_ids) >= 2


def test_degree_one_spur_is_not_a_backbone_node() -> None:
    """A degree-one spur is never selected as a backbone node."""
    assert "P6" not in ARTIFACTS.design.backbone_ids


def test_backbone_meets_the_mesh_link_target() -> None:
    """Every backbone node wires to its configured number of nearest peers on the mesh."""
    assert ARTIFACTS.validation["backbone_meets_mesh_link_target"] is True


def test_design_is_connected() -> None:
    """The whole ring design validates as a single connected component."""
    assert ARTIFACTS.validation["connected"] is True


def test_backbone_survives_any_single_city() -> None:
    """The ring backbone's physical fiber has no single-city chokepoint (biconnected)."""
    assert ARTIFACTS.validation["backbone_mesh_two_vertex_connected"] is True


def test_every_meshed_ring_node_holds_its_links_independently() -> None:
    """Each seated ring PoP holds two mesh links no single city's loss can both take."""
    assert UNFORCED_RING.validation["backbone_meets_independent_mesh_link_target"] is True


def test_the_ring_cannot_meet_a_degree_its_fiber_cannot_carry() -> None:
    """Asking three independent links of two-direction fiber is refused, naming the node.

    The configured degree is a count of links that fail independently, so a graph that
    cannot carry it is refused rather than reported: no PoP on a ring has a third way out.
    """
    params = replace(_MESHED_RING, tuning=Tuning(backbone_mesh_degree=3))
    with pytest.raises(ValueError, match="independently failing backbone mesh links at"):
        fixtures.forced_link_artifacts(params, OperatorLinks())


# The ring with four chords, so P0 through P4 each have a third fiber direction and P5
# keeps only its two ring neighbours. At a mesh degree of three P5 is the one node the
# fiber cannot carry: the spur an operator exempts, with every other node meeting the
# degree, which is what makes the exemption's effect legible here.
_CHORDED_PAIRS = {
    ("P0", "P1"): 100.0, ("P1", "P2"): 100.0, ("P2", "P3"): 100.0,
    ("P3", "P4"): 100.0, ("P4", "P5"): 100.0, ("P5", "P0"): 100.0,
    ("P0", "P2"): 100.0, ("P0", "P3"): 100.0, ("P1", "P3"): 100.0, ("P2", "P4"): 100.0,
}
_CHORDED_BACKBONE = ("P0", "P1", "P2", "P3", "P4", "P5")


def _chorded_design(exempt: tuple[str, ...] = ()) -> DesignArtifacts:
    """Synthesize the chorded ring at a mesh degree of three, exempting the named nodes."""
    vertices = [
        fixtures.carrier_pop(name, *fixtures.RING_COORDS[name]) for name in _CHORDED_BACKBONE
    ]
    params = DesignParams(
        min_backbone_count=2,
        forced_backbone_names=_CHORDED_BACKBONE,
        degree_exempt_backbone_names=exempt,
        datacenter_cities=fixtures.ring_datacenter_cities(),
        tuning=Tuning(backbone_mesh_degree=3),
    )
    return run_design(vertices, fixtures.physical_edges_from(_CHORDED_PAIRS), params)


EXEMPT_SPUR = _chorded_design(("P5",))


def test_the_chorded_ring_is_refused_at_its_one_spur() -> None:
    """Without the exemption the same design is refused, naming the two-direction node."""
    with pytest.raises(ValueError, match="independently failing backbone mesh links at: P5"):
        _chorded_design()


def test_exempting_the_spur_lets_the_design_finalize() -> None:
    """With P5 exempt the mesh target is met, so the design the operator wanted is built."""
    assert EXEMPT_SPUR.validation["backbone_meets_independent_mesh_link_target"] is True


def test_the_exempt_spur_is_named_in_the_finished_report() -> None:
    """The published report says which node the degree was not asked of."""
    assert EXEMPT_SPUR.validation["backbone_degree_exempt"] == [{"id": "P5", "name": "P5"}]


def test_the_exempt_spur_is_still_meshed_into_the_backbone() -> None:
    """Exempting P5 thins it to the two links its fiber allows rather than stranding it."""
    pairs = backbone_mesh_pairs(EXEMPT_SPUR.design)
    assert len([pair for pair in pairs if "P5" in pair]) == 2


def _forced_off_net_artifacts() -> DesignArtifacts:
    """Synthesize over the ring with an off-net site forced as a backbone node."""
    site, params = fixtures.forced_off_net_case()
    return run_design(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(), params, off_net_sites=[site]
    )


def test_forced_off_net_site_is_seated_in_the_backbone() -> None:
    """A forced off-net site's local-fiber twin lands in the backbone."""
    design = _forced_off_net_artifacts().design
    assert any(node.startswith("offnet_") for node in design.backbone_ids)


def test_off_net_design_validates_connected() -> None:
    """A design with an off-net backbone twin validates as a connected whole."""
    artifacts = _forced_off_net_artifacts()
    assert artifacts.validation["connected"] is True


CONVERGENCE_HUB = fixtures.convergence_hub_artifacts()
NON_DATACENTER_HUB = fixtures.convergence_hub_artifacts(promote_hub=False)


def test_promoted_convergence_hub_is_seated_in_the_backbone() -> None:
    """The data-center transit hub carrying >= 3 lines is promoted into the backbone."""
    assert "hub_dc" in CONVERGENCE_HUB.design.backbone_ids


def test_promoted_convergence_design_validates_connected() -> None:
    """The design with the promoted hub still validates end-to-end as connected."""
    assert CONVERGENCE_HUB.validation["connected"] is True


def test_convergence_promotion_reaches_a_fixpoint() -> None:
    """The returned design is stable: a further convergence pass promotes nothing."""
    carrier_pops = [v for v in CONVERGENCE_HUB.vertices if is_carrier_pop(v)]
    cities = frozenset(
        (pop.info.municipality, pop.info.state) for pop in carrier_pops
    )
    assert convergence_promotion_ids(CONVERGENCE_HUB.design, carrier_pops, cities) == set()


def test_non_data_center_convergence_hub_is_not_promoted() -> None:
    """The same >= 3-line crossing with no data center is never promoted to backbone."""
    assert "hub_dc" not in NON_DATACENTER_HUB.design.backbone_ids


def test_non_data_center_convergence_hub_stays_transit() -> None:
    """The unpromoted >= 3-line crossing remains a transit node in the design."""
    assert "hub_dc" in NON_DATACENTER_HUB.design.transit_ids


def _open_gate_artifacts() -> DesignArtifacts:
    """Synthesize over the ring with the gate open (datacenter_cities=None) and P3 forced.

    ``datacenter_cities=None`` is the operator's free-for-all: no data-center set is
    supplied at all, so a forced PoP would be rejected under the default gate yet is
    accepted here. Drives the full deployed pipeline (dual-home -> overrides ->
    synthesize -> finalize) via ``run_design``.
    """
    params = DesignParams(
        min_backbone_count=2, forced_backbone_names=("P3",), datacenter_cities=None
    )
    return run_design(fixtures.ring_vertices(), fixtures.ring_physical_edges(), params)


def test_open_gate_seats_a_forced_non_data_center_backbone() -> None:
    """With the gate open, a forced PoP at no data-center city is seated in the backbone."""
    assert "P3" in _open_gate_artifacts().design.backbone_ids


def test_open_gate_design_validates_connected() -> None:
    """The open-gate design validates end-to-end as a single connected component."""
    assert _open_gate_artifacts().validation["connected"] is True
