from __future__ import annotations

import pytest

import fixtures
from synthesizer.model import SynthesisParams, RoleExclusions, RoleOverrides
from synthesizer.synthesize import synthesize_two_tier
from synthesizer.overrides import apply_role_overrides

pop = fixtures.carrier_pop
physical = fixtures.fiber_segments_from


def test_apply_role_overrides_resolves_prohibited_backbone() -> None:
    params = SynthesisParams(exclusions=RoleExclusions(prohibited_backbone_names=("P0",)))
    _sites, _links, overrides = apply_role_overrides(
        [pop("P0"), pop("P1")], physical({("P0", "P1"): 1.0}), params
    )
    assert overrides.prohibited_backbone_ids == frozenset({"P0"})


def test_apply_role_overrides_rejects_an_unknown_prohibited_name() -> None:
    params = SynthesisParams(exclusions=RoleExclusions(prohibited_backbone_names=("Nowhere",)))
    with pytest.raises(ValueError):
        apply_role_overrides([pop("P0")], physical({("P0", "P1"): 1.0}), params)


def test_synthesize_bars_a_prohibited_pop_from_the_backbone() -> None:
    synthesis = synthesize_two_tier(
        fixtures.ring_sites(),
        fixtures.ring_fiber_segments(),
        SynthesisParams(
            min_backbone_count=2),
        RoleOverrides(prohibited_backbone_ids=frozenset({"P3"})),
    )
    assert "P3" not in synthesis.backbone_ids
