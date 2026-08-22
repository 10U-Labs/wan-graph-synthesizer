from __future__ import annotations

import pytest

import fixtures
from synthesizer.offnet import SeatedOffNetSites, realize_off_net_sites
from synthesizer.model import is_carrier_pop
from synthesizer.input_graph import Site

def _realize(
    *sites: Site,
    forced: frozenset[str] = frozenset(),
) -> SeatedOffNetSites:
    return realize_off_net_sites(fixtures.carrier_pops_in_a_column(), {}, list(sites), forced)


def test_realize_seats_a_forced_site() -> None:
    result = _realize(fixtures.off_net_site("dulles", 0.0, 0.5), forced=frozenset({"dulles"}))
    assert len(result.seat_ids) == 1


def test_seated_twin_id_carries_the_off_net_prefix() -> None:
    result = _realize(fixtures.off_net_site("dulles", 0.0, 0.5), forced=frozenset({"dulles"}))
    assert next(iter(result.seat_ids)).startswith("offnet_")


def test_realize_adds_local_fiber_links() -> None:
    result = _realize(fixtures.off_net_site("dulles", 0.0, 0.5), forced=frozenset({"dulles"}))
    assert len(result.fiber_segments) == 3


def test_seated_twin_is_a_carrier_pop() -> None:
    result = _realize(fixtures.off_net_site("dulles", 0.0, 0.5), forced=frozenset({"dulles"}))
    seat_id = next(iter(result.seat_ids))
    assert is_carrier_pop(next(v for v in result.sites if v.id == seat_id)) is True


def test_realize_ignores_unforced_sites() -> None:
    result = _realize(fixtures.off_net_site("dulles", 0.0, 0.5))
    assert result.seat_ids == frozenset()


def test_isolated_forced_site_raises() -> None:
    with pytest.raises(ValueError):
        _realize(fixtures.off_net_site("remote", 0.0, 10.0), forced=frozenset({"remote"}))


def test_a_forced_site_that_is_already_a_carrier_pop_is_rejected() -> None:
    with pytest.raises(ValueError, match="already a carrier PoP: P0"):
        _realize(fixtures.off_net_site("P0", 0.0, 0.5), forced=frozenset({"P0"}))
