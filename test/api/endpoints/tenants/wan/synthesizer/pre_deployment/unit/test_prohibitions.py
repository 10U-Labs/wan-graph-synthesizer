"""Unit tests for barring a PoP from the backbone (prohibited_backbone)."""

from __future__ import annotations

import pytest

import fixtures
from synthesizer.model import DesignParams, RoleExclusions, RoleOverrides
from synthesizer.synthesize import synthesize_two_tier_design
from synthesizer.overrides import apply_role_overrides

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from


def test_apply_role_overrides_resolves_prohibited_backbone() -> None:
    """A prohibited-backbone name resolves to its vertex id in the overrides."""
    params = DesignParams(exclusions=RoleExclusions(prohibited_backbone_names=("P0",)))
    _vertices, _edges, overrides = apply_role_overrides(
        [pop("P0"), pop("P1")], physical({("P0", "P1"): 1.0}), params
    )
    assert overrides.prohibited_backbone_ids == frozenset({"P0"})


def test_apply_role_overrides_rejects_an_unknown_prohibited_name() -> None:
    """An unknown prohibited-backbone PoP name is rejected, not silently dropped."""
    params = DesignParams(exclusions=RoleExclusions(prohibited_backbone_names=("Nowhere",)))
    with pytest.raises(ValueError):
        apply_role_overrides([pop("P0")], physical({("P0", "P1"): 1.0}), params)


def test_synthesize_bars_a_prohibited_pop_from_the_backbone() -> None:
    """A prohibited-backbone override keeps that PoP out of the selected backbone."""
    design = synthesize_two_tier_design(
        fixtures.ring_vertices(),
        fixtures.ring_physical_edges(),
        DesignParams(
            min_backbone_count=2, datacenter_cities=fixtures.ring_datacenter_cities()
        ),
        RoleOverrides(prohibited_backbone_ids=frozenset({"P3"})),
    )
    assert "P3" not in design.backbone_ids
