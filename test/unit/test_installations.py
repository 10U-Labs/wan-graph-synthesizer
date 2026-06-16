"""Unit tests for synthesizing aggregation facilities from justified installations."""

from __future__ import annotations

import fixtures
from wan_designer.installations import RealizedInstallations, realize_installations
from wan_designer.model import Vertex, is_carrier_pop


def _pops() -> list[Vertex]:
    """Three closely spaced carrier PoPs the facility twins can home to."""
    return [
        fixtures.carrier_pop("P0", 0.0, 0.0),
        fixtures.carrier_pop("P1", 0.0, 1.0),
        fixtures.carrier_pop("P2", 0.0, 2.0),
    ]


def _realize(*extra: Vertex, forced: frozenset[str] = frozenset()) -> RealizedInstallations:
    """Realize installations over the three PoPs plus the given extra vertices."""
    return realize_installations([*_pops(), *extra], {}, forced)


def test_realize_installations_seats_a_forced_twin() -> None:
    """A forced justified installation near carrier PoPs gets a co-located twin."""
    result = _realize(fixtures.justified_installation("luke", 0.0, 0.5), forced=frozenset({"luke"}))
    assert result.facility_ids == frozenset({"fac_luke"})


def test_realize_installations_adds_backbone_edges() -> None:
    """The facility twin gains synthetic links to its nearest carrier PoPs."""
    result = _realize(fixtures.justified_installation("luke", 0.0, 0.5), forced=frozenset({"luke"}))
    assert len(result.physical_edges) == 3


def test_realize_installations_twin_is_a_carrier_pop() -> None:
    """The twin is a carrier PoP, so it flows through the backbone machinery."""
    result = _realize(fixtures.justified_installation("luke", 0.0, 0.5), forced=frozenset({"luke"}))
    assert is_carrier_pop(next(v for v in result.vertices if v.id == "fac_luke")) is True


def test_realize_installations_ignores_unforced_installations() -> None:
    """A justified installation the operator did not force stays demand-only."""
    result = _realize(fixtures.justified_installation("luke", 0.0, 0.5))
    assert result.facility_ids == frozenset()


def test_realize_installations_ignores_unjustified_sites() -> None:
    """A forced but not-justified installation never becomes a facility."""
    result = _realize(fixtures.access_vertex("plain", 0.0, 0.5), forced=frozenset({"plain"}))
    assert result.facility_ids == frozenset()


def test_realize_installations_skips_isolated_installation() -> None:
    """A forced site with no PoP in range stays demand-only (no twin)."""
    result = _realize(
        fixtures.justified_installation("remote", 0.0, 10.0), forced=frozenset({"remote"})
    )
    assert result.facility_ids == frozenset()


def test_realize_installations_collapses_colocated_sites() -> None:
    """Two forced sites at one location collapse to a single twin."""
    result = _realize(
        fixtures.justified_installation("hill", 0.0, 0.5),
        fixtures.justified_installation("ogden", 0.0, 0.5),
        forced=frozenset({"hill", "ogden"}),
    )
    assert len(result.facility_ids) == 1


def test_realize_installations_avoids_id_collision() -> None:
    """A facility id already taken by another vertex is suffixed to stay unique."""
    result = _realize(
        fixtures.carrier_pop("fac_luke", 0.0, 0.5),
        fixtures.justified_installation("luke", 0.0, 0.6),
        forced=frozenset({"luke"}),
    )
    assert "fac_luke_2" in result.facility_ids
