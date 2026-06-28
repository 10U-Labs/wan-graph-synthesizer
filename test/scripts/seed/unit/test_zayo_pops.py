"""Data-integrity checks for the worldwide Zayo carrier graph.

The Zayo PoPs and links are digitized from the mapbook's network maps, so they span
the globe. These guard the invariants that keep that graph usable: every PoP has a
distinct ``(municipality, state)`` key, overseas PoPs carry their country, every PoP
is named by at least one edge (or the substrate loader silently drops it), no edge
dangles to a city that is not a PoP, and every intercontinental link rides one of the
cities the maps draw a submarine cable to.
"""

from __future__ import annotations

import csv

from repo_utils import REPO_ROOT

_DATA = REPO_ROOT / "data"
_ZAYO = _DATA / "vertices" / "carriers" / "zayo.csv"
_ZAYO_EDGES = _DATA / "edges" / "zayo.csv"

# Country -> continent. Same-continent links (Canada<->US land borders, intra-Europe,
# intra-Asia) are not submarine crossings, so they are out of the gateway rule below.
_CONTINENT = {
    "United States": "North America",
    "Canada": "North America",
    "Austria": "Europe",
    "Belgium": "Europe",
    "France": "Europe",
    "Germany": "Europe",
    "Ireland": "Europe",
    "Italy": "Europe",
    "Luxembourg": "Europe",
    "Netherlands": "Europe",
    "Spain": "Europe",
    "Switzerland": "Europe",
    "United Kingdom": "Europe",
    "Japan": "Asia",
    "Hong Kong": "Asia",
    "Singapore": "Asia",
    "Australia": "Oceania",
    "Brazil": "South America",
}

# The cities the mapbook draws an intercontinental (submarine) cable to. A cross-ocean
# edge may only connect two of these -- everywhere else reaches another continent by
# routing terrestrially to one of them first.
_GATEWAYS = {
    ("New York", "NY"), ("Ashburn", "VA"), ("Seattle", "WA"),
    ("San Jose", "CA"), ("Los Angeles", "CA"), ("Miami", "FL"),
    ("Manchester", ""), ("London", ""), ("Paris", ""),
    ("Frankfurt", ""), ("Marseille", ""),
    ("Tokyo", ""), ("Hong Kong", ""), ("Singapore", ""), ("Sydney", ""),
    ("Sao Paulo", ""),
}


def _pops() -> list[dict[str, str]]:
    """The Zayo vertex rows."""
    with _ZAYO.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _edge_rows() -> list[dict[str, str]]:
    """The Zayo edge rows."""
    with _ZAYO_EDGES.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _edge_endpoints() -> set[tuple[str, str]]:
    """Every ``(municipality, state)`` that a Zayo edge names as an endpoint."""
    rows = _edge_rows()
    near = {(row["A_Municipality"], row["A_State"]) for row in rows}
    return near | {(row["Z_Municipality"], row["Z_State"]) for row in rows}


def _edge_pairs() -> set[tuple[tuple[str, str], tuple[str, str]]]:
    """Every edge as a ``((a_muni, a_state), (z_muni, z_state))`` pair."""
    return {
        ((row["A_Municipality"], row["A_State"]), (row["Z_Municipality"], row["Z_State"]))
        for row in _edge_rows()
    }


def _continent(key: tuple[str, str]) -> str:
    """The continent of a PoP key, via its country in the vertex file."""
    country = {(pop["Municipality"], pop["State"]): pop["Country"] for pop in _pops()}
    return _CONTINENT[country[key]]


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


def test_intercontinental_edges_use_submarine_gateways() -> None:
    """A cross-continent edge connects only cities the map gives a submarine cable."""
    offenders = {
        (a, z) for a, z in _edge_pairs()
        if _continent(a) != _continent(z) and not ({a, z} <= _GATEWAYS)
    }
    assert not offenders
