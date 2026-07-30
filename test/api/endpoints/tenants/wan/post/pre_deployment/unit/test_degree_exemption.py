"""Unit tests for exempting a backbone node from the mesh degree.

These pin the resolution step: the operator writes PoP names, and the search reads ids.
What an exemption then does to selection and to validation is pinned with those units.
"""

from __future__ import annotations

import pytest

import fixtures
from synthesizer.model import DesignParams
from synthesizer.overrides import apply_role_overrides

pop = fixtures.carrier_pop
physical = fixtures.physical_edges_from


def test_apply_role_overrides_resolves_a_degree_exempt_name() -> None:
    """A degree-exempt name resolves to its vertex id in the overrides."""
    params = DesignParams(degree_exempt_backbone_names=("P0",))
    _vertices, _edges, overrides = apply_role_overrides(
        [pop("P0"), pop("P1")], physical({("P0", "P1"): 1.0}), params
    )
    assert overrides.degree_exempt_backbone_ids == frozenset({"P0"})


def test_apply_role_overrides_exempts_nobody_by_default() -> None:
    """A design naming no exempt node holds every backbone node to the degree."""
    _vertices, _edges, overrides = apply_role_overrides(
        [pop("P0"), pop("P1")], physical({("P0", "P1"): 1.0}), DesignParams()
    )
    assert overrides.degree_exempt_backbone_ids == frozenset()


def test_apply_role_overrides_rejects_an_unknown_degree_exempt_name() -> None:
    """An unknown degree-exempt PoP name is rejected, not silently dropped."""
    params = DesignParams(degree_exempt_backbone_names=("Nowhere",))
    with pytest.raises(ValueError, match="degree_exempt_backbone"):
        apply_role_overrides([pop("P0")], physical({("P0", "P1"): 1.0}), params)
