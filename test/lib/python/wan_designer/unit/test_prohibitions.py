"""Unit tests for per-tier role prohibition (prohibited_cores)."""

from __future__ import annotations

import fixtures
from wan_graph.model import DesignParams, RoleExclusions, RoleOverrides
from wan_designer.optimize import optimize_three_tier_design
from wan_designer.overrides import apply_role_overrides

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from


def test_apply_role_overrides_resolves_prohibited_cores() -> None:
    """A prohibited-core name resolves to its vertex id in the overrides."""
    params = DesignParams(exclusions=RoleExclusions(prohibited_core_names=("P",)))
    _vertices, _edges, overrides = apply_role_overrides(
        [pop("P"), pop("z")], physical({("P", "z"): 1.0}), params
    )
    assert overrides.prohibited_core_ids == frozenset({"P"})


def test_apply_role_overrides_allows_a_forced_aggregation_prohibited_from_core() -> None:
    """A PoP may be both a forced aggregation and barred from the core tier."""
    params = DesignParams(
        forced_aggregation_names=("P",),
        exclusions=RoleExclusions(prohibited_core_names=("P",)),
    )
    _vertices, _edges, overrides = apply_role_overrides(
        [pop("P"), pop("z")], physical({("P", "z"): 1.0}), params
    )
    assert "P" in overrides.forced_aggregation_ids & overrides.prohibited_core_ids


def test_optimize_bars_a_prohibited_core_from_the_core_tier() -> None:
    """A prohibited-core override keeps that PoP out of the selected core tier."""
    design = optimize_three_tier_design(
        fixtures.ring_vertices(), fixtures.ring_physical_edges(),
        DesignParams(min_core_count=2), RoleOverrides(prohibited_core_ids=frozenset({"P3"})),
    )
    assert "P3" not in design.core_ids
