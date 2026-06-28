"""Data-integrity checks for the worldwide Zayo carrier graph.

The Zayo vertices are merged from the mapbook's text IP PoP List, so they span the
globe, and the subsea/core routes wire the overseas hubs into the substrate. These
guard the invariants that keep that graph usable: every PoP has a distinct
``(municipality, state)`` key, overseas PoPs carry their country, and the overseas
hubs are edge-connected to endpoints that resolve back to real PoPs -- otherwise the
substrate loader would drop them.
"""

from __future__ import annotations

import csv

from repo_utils import REPO_ROOT

_DATA = REPO_ROOT / "data"
_ZAYO = _DATA / "vertices" / "carriers" / "zayo.csv"
_ZAYO_EDGES = _DATA / "edges" / "zayo.csv"

# Overseas hub PoPs the subsea/core edges must connect, so they survive substrate load.
_HUBS = {
    ("Tokyo", ""),
    ("London", ""),
    ("Paris", ""),
    ("Frankfurt", ""),
    ("Amsterdam", ""),
    ("Sydney", ""),
    ("Singapore", ""),
    ("Hong Kong", ""),
    ("Sao Paulo", ""),
}


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


def test_overseas_hubs_are_edge_connected() -> None:
    """Every overseas hub is named by a Zayo edge, so the substrate keeps it."""
    assert _HUBS <= _edge_endpoints()


def test_edge_endpoints_resolve_to_pops() -> None:
    """No Zayo edge dangles: every endpoint is a real PoP ``(municipality, state)``."""
    keys = {(pop["Municipality"], pop["State"]) for pop in _pops()}
    assert _edge_endpoints() <= keys
