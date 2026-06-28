"""Data-integrity checks for the worldwide Zayo carrier graph.

The Zayo PoPs and links are digitized from the mapbook's network maps, so they span
the globe. These guard the invariants that keep that graph usable: every PoP has a
distinct ``(municipality, state)`` key, overseas PoPs carry their country, every PoP
is named by at least one edge (or the substrate loader silently drops it), and no
edge dangles to a city that is not a PoP.
"""

from __future__ import annotations

import csv

from repo_utils import REPO_ROOT

_DATA = REPO_ROOT / "data"
_ZAYO = _DATA / "vertices" / "carriers" / "zayo.csv"
_ZAYO_EDGES = _DATA / "edges" / "zayo.csv"


def _pops() -> list[dict[str, str]]:
    """The Zayo vertex rows."""
    with _ZAYO.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _edge_endpoints() -> set[tuple[str, str]]:
    """Every ``(municipality, state)`` that a Zayo edge names as an endpoint."""
    with _ZAYO_EDGES.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    near = {(row["A_Municipality"], row["A_State"]) for row in rows}
    return near | {(row["Z_Municipality"], row["Z_State"]) for row in rows}


def test_city_keys_are_unique() -> None:
    """No two Zayo PoPs share a ``(municipality, state)`` key."""
    keys = [(pop["Municipality"], pop["State"]) for pop in _pops()]
    assert len(keys) == len(set(keys))


def test_overseas_pops_carry_their_country() -> None:
    """Representative overseas IP PoPs are present with their country set."""
    located = {(pop["Municipality"], pop["Country"]) for pop in _pops()}
    overseas = {
        ("Tokyo", "Japan"),
        ("London", "United Kingdom"),
        ("Sao Paulo", "Brazil"),
        ("Sydney", "Australia"),
    }
    assert overseas <= located


def test_every_pop_is_connected() -> None:
    """Every Zayo PoP is named by an edge, so the substrate loader keeps all of them."""
    keys = {(pop["Municipality"], pop["State"]) for pop in _pops()}
    assert keys <= _edge_endpoints()


def test_edge_endpoints_resolve_to_pops() -> None:
    """No Zayo edge dangles: every endpoint is a real PoP ``(municipality, state)``."""
    keys = {(pop["Municipality"], pop["State"]) for pop in _pops()}
    assert _edge_endpoints() <= keys
