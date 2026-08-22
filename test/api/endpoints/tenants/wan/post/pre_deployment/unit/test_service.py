from __future__ import annotations

import fixtures
from synthesizer.model import SynthesisParams
from fixtures import run_synthesis


def test_run_synthesis_is_connected() -> None:
    artifacts = run_synthesis(
        fixtures.ring_sites(), fixtures.ring_fiber_segments(), fixtures.ring_params()
    )
    assert artifacts.validation["connected"] is True


def test_run_synthesis_honors_a_forced_backbone_pop() -> None:
    synthesis = run_synthesis(
        fixtures.ring_sites(),
        fixtures.ring_fiber_segments(),
        SynthesisParams(
            min_backbone_count=2,
            forced_backbone_names=("P3",),
        ),
    ).synthesis
    assert "P3" in synthesis.backbone_ids


def test_run_synthesis_seats_a_forced_off_net_site_as_backbone() -> None:
    site = fixtures.off_net_site("Dulles Hub", 40.5, -100.0)
    synthesis = run_synthesis(
        fixtures.ring_sites(),
        fixtures.ring_fiber_segments(),
        SynthesisParams(
            min_backbone_count=2,
            forced_backbone_names=("Dulles Hub",),
        ),
        off_net_sites=[site],
    ).synthesis
    assert any(node.startswith("offnet_") for node in synthesis.backbone_ids)
