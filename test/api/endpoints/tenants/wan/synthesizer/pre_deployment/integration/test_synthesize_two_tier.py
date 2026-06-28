"""Integration test: the synthesizer over the synthetic ring graph.

A six-PoP ring is 2-connected, so it meshes into a resilient backbone; a degree-one
spur confirms such PoPs are never backbone nodes. The ring carries carrier PoPs only --
in the two-tier model demand homes to the backbone over the physical graph, so demand
homing is exercised at the unit level (see ``test_synthesize.py``).
"""

from __future__ import annotations

import fixtures
from fixtures import run_design
from synthesizer.input_graph import edge_key
from synthesizer.model import DesignArtifacts, DesignParams, ForcedConnection, is_carrier_pop
from synthesizer.synthesize import convergence_promotion_ids
from synthesizer.validation import backbone_mesh_pairs

ARTIFACTS = fixtures.ring_artifacts()
FORCED = fixtures.forced_backbone_artifacts("P3")
FORCED_ROADM = fixtures.forced_roadm_backbone_artifacts("P3")
PROHIBITED = fixtures.prohibited_backbone_artifacts("P4")

# A forced backbone-backbone link over the ring, resolved through the operator-pin path
# so the asserted edge reflects a genuinely honored request.
FORCED_BACKBONE_LINK = fixtures.forced_connection_artifacts(
    DesignParams(
        min_backbone_count=2,
        forced_backbone_names=("P0", "P3"),
        datacenter_cities=fixtures.ring_datacenter_cities(),
    ),
    (ForcedConnection("backbone-backbone", "P0", "P3"),),
)


def test_forced_backbone_connection_appears_in_the_mesh() -> None:
    """A forced backbone-backbone connection is present in the routed backbone mesh."""
    assert edge_key("P0", "P3") in backbone_mesh_pairs(FORCED_BACKBONE_LINK.design)


def test_forced_pop_is_placed_in_the_backbone() -> None:
    """A PoP named on the force-backbone list is honored as a backbone node."""
    assert "P3" in FORCED.design.backbone_ids


def test_forced_roadm_is_seated_in_the_backbone() -> None:
    """A pinned ROADM is honored as a backbone node.

    ROADMs are eligible like any other point, and a force always wins regardless; this
    is the mechanism the Joint Great Falls and Minot ROADM pins rely on.
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


def test_promoted_convergence_design_validates_connected() -> None:
    """The design with the promoted hub still validates end-to-end as connected."""
    assert "hub_dc" in CONVERGENCE_HUB.design.backbone_ids
    assert CONVERGENCE_HUB.validation["connected"] is True


def test_convergence_promotion_reaches_a_fixpoint() -> None:
    """The returned design is stable: a further convergence pass promotes nothing."""
    carrier_pops = [v for v in CONVERGENCE_HUB.vertices if is_carrier_pop(v)]
    cities = frozenset(
        (pop.info.municipality, pop.info.state) for pop in carrier_pops
    )
    assert convergence_promotion_ids(CONVERGENCE_HUB.design, carrier_pops, cities) == set()


def test_non_data_center_convergence_hub_stays_transit() -> None:
    """The same >= 3-line crossing with no data center is never promoted."""
    design = NON_DATACENTER_HUB.design
    assert "hub_dc" not in design.backbone_ids
    assert "hub_dc" in design.transit_ids
