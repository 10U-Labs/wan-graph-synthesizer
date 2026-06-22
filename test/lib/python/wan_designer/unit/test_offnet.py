"""Unit tests for seating operator-forced off-net locations via local fiber."""

from __future__ import annotations

from pathlib import Path

import pytest

import fixtures
from seed import load_off_net_sites
from wan_designer.offnet import RealizedOffNet, realize_off_net_sites
from wan_designer.model import is_carrier_pop
from wan_graph.model import Vertex


def _pops() -> list[Vertex]:
    """Three closely spaced carrier PoPs an off-net twin can home to."""
    return [
        fixtures.carrier_pop("P0", 0.0, 0.0),
        fixtures.carrier_pop("P1", 0.0, 1.0),
        fixtures.carrier_pop("P2", 0.0, 2.0),
    ]


def _realize(*sites: Vertex, forced: frozenset[str] = frozenset()) -> RealizedOffNet:
    """Realize the given off-net sites against the three carrier PoPs."""
    return realize_off_net_sites(_pops(), {}, list(sites), forced)


def test_realize_seats_a_forced_site() -> None:
    """A forced off-net site near carrier PoPs is seated as a local-fiber twin."""
    result = _realize(fixtures.off_net_site("dulles", 0.0, 0.5), forced=frozenset({"dulles"}))
    assert len(result.seat_ids) == 1


def test_seated_twin_id_carries_the_off_net_prefix() -> None:
    """The seated twin's id is namespaced with the off-net prefix."""
    result = _realize(fixtures.off_net_site("dulles", 0.0, 0.5), forced=frozenset({"dulles"}))
    assert next(iter(result.seat_ids)).startswith("offnet_")


def test_realize_adds_local_fiber_edges() -> None:
    """The twin gains synthetic local-fiber links to its nearest carrier PoPs."""
    result = _realize(fixtures.off_net_site("dulles", 0.0, 0.5), forced=frozenset({"dulles"}))
    assert len(result.physical_edges) == 3


def test_seated_twin_is_a_carrier_pop() -> None:
    """The twin is a carrier PoP, so it flows through the backbone machinery."""
    result = _realize(fixtures.off_net_site("dulles", 0.0, 0.5), forced=frozenset({"dulles"}))
    seat_id = next(iter(result.seat_ids))
    assert is_carrier_pop(next(v for v in result.vertices if v.id == seat_id)) is True


def test_realize_ignores_unforced_sites() -> None:
    """An off-net site the operator did not force is never seated."""
    result = _realize(fixtures.off_net_site("dulles", 0.0, 0.5))
    assert result.seat_ids == frozenset()


def test_isolated_forced_site_raises() -> None:
    """A forced site with too few carrier PoPs in range fails loudly."""
    with pytest.raises(ValueError):
        _realize(fixtures.off_net_site("remote", 0.0, 10.0), forced=frozenset({"remote"}))


def test_name_colliding_with_a_carrier_pop_raises() -> None:
    """A forced off-net name that is also a carrier PoP is ambiguous and rejected."""
    with pytest.raises(ValueError):
        _realize(fixtures.off_net_site("P0", 0.0, 0.5), forced=frozenset({"P0"}))


def test_load_off_net_sites_reads_coordinates(tmp_path: Path) -> None:
    """The loader parses name and coordinates into a site vertex."""
    path = tmp_path / "off_net.csv"
    path.write_text('name,latitude,longitude\n"Dulles, VA",38.95,-77.46\n', encoding="utf-8")
    assert load_off_net_sites(path)[0].coords == (38.95, -77.46)


def test_load_off_net_sites_missing_file_raises(tmp_path: Path) -> None:
    """A configured off-net file that does not exist is reported as an error."""
    with pytest.raises(ValueError):
        load_off_net_sites(tmp_path / "absent.csv")
