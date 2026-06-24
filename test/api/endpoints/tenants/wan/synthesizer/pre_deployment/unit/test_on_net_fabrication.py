"""Unit tests for fabricating on-net nodes from operator-forced locations."""

from __future__ import annotations

import fixtures
from synthesizer.on_net_fabrication import (
    FabricatedOnNetNodes,
    fabricate_missing_on_net_nodes,
)
from synthesizer.model import is_carrier_pop
from synthesizer.input_graph import Vertex


def _pops() -> list[Vertex]:
    """Three closely spaced carrier PoPs the fabricated twins can home to."""
    return [
        fixtures.carrier_pop("P0", 0.0, 0.0),
        fixtures.carrier_pop("P1", 0.0, 1.0),
        fixtures.carrier_pop("P2", 0.0, 2.0),
    ]


def _fabricate(*extra: Vertex, forced: frozenset[str] = frozenset()) -> FabricatedOnNetNodes:
    """Fabricate on-net nodes over the three PoPs plus the given extra vertices."""
    return fabricate_missing_on_net_nodes([*_pops(), *extra], {}, forced)


def test_fabricates_a_forced_twin() -> None:
    """A forced location near carrier PoPs gets a co-located on-net twin."""
    result = _fabricate(
        fixtures.access_vertex("luke", 0.0, 0.5), forced=frozenset({"luke"})
    )
    assert result.on_net_ids == frozenset({"fac_luke"})


def test_fabrication_adds_backbone_edges() -> None:
    """The fabricated twin gains synthetic links to its nearest carrier PoPs."""
    result = _fabricate(
        fixtures.access_vertex("luke", 0.0, 0.5), forced=frozenset({"luke"})
    )
    assert len(result.physical_edges) == 3


def test_fabricated_twin_is_a_carrier_pop() -> None:
    """The twin is a carrier PoP, so it flows through the backbone machinery."""
    result = _fabricate(
        fixtures.access_vertex("luke", 0.0, 0.5), forced=frozenset({"luke"})
    )
    assert is_carrier_pop(next(v for v in result.vertices if v.id == "fac_luke")) is True


def test_ignores_unforced_locations() -> None:
    """A location the operator did not force stays demand-only."""
    result = _fabricate(fixtures.access_vertex("luke", 0.0, 0.5))
    assert result.on_net_ids == frozenset()


def test_fabricates_a_forced_remote_location_regardless_of_distance() -> None:
    """A forced location with no nearby public fiber is still fabricated (no radius cap)."""
    result = _fabricate(
        fixtures.access_vertex("remote", 0.0, 10.0), forced=frozenset({"remote"})
    )
    assert result.on_net_ids == frozenset({"fac_remote"})


def test_collapses_colocated_sites() -> None:
    """Two forced sites at one location collapse to a single twin."""
    result = _fabricate(
        fixtures.access_vertex("hill", 0.0, 0.5),
        fixtures.access_vertex("ogden", 0.0, 0.5),
        forced=frozenset({"hill", "ogden"}),
    )
    assert len(result.on_net_ids) == 1


def test_demand_only_when_too_few_carrier_pops() -> None:
    """A forced location with fewer than two carrier PoPs to wire to stays demand-only."""
    result = fabricate_missing_on_net_nodes(
        [fixtures.carrier_pop("P0", 0.0, 0.0), fixtures.access_vertex("luke", 0.0, 0.5)],
        {},
        frozenset({"luke"}),
    )
    assert result.on_net_ids == frozenset()


def test_avoids_id_collision() -> None:
    """A twin id already taken by another vertex is suffixed to stay unique."""
    result = _fabricate(
        fixtures.carrier_pop("fac_luke", 0.0, 0.5),
        fixtures.access_vertex("luke", 0.0, 0.6),
        forced=frozenset({"luke"}),
    )
    assert "fac_luke_2" in result.on_net_ids
