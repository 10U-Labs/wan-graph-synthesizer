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

# Country -> continent. Same-continent links (intra-Europe, intra-Asia) are not
# submarine crossings, so they are out of the gateway rule below.
_CONTINENT = {
    "United States": "North America",
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

# The cities the mapbook draws an intercontinental cable to -- the Subsea Routes
# section plus the Global IP Network map's APAC inset, which lands trans-Pacific and
# intra-APAC cables at Hong Kong. A cross-ocean edge may only connect two of these --
# everywhere else reaches another continent by routing terrestrially to one first.
_GATEWAYS = {
    ("New York", "NY"), ("Ashburn", "VA"), ("Seattle", "WA"), ("Hillsboro", "OR"),
    ("San Jose", "CA"), ("Los Angeles", "CA"), ("Tuckerton", "NJ"),
    ("Manchester", ""), ("London", ""), ("Slough", ""), ("Paris", ""),
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


def _domestic_neighbours(city: tuple[str, str]) -> set[tuple[str, str]]:
    """The US PoPs one Zayo span away from ``city``."""
    country = {(pop["Municipality"], pop["State"]): pop["Country"] for pop in _pops()}
    linked = set()
    for near, far in _edge_pairs():
        if near == city:
            linked.add(far)
        elif far == city:
            linked.add(near)
    return {other for other in linked if country.get(other) == "United States"}


def test_portland_metro_is_a_through_junction() -> None:
    """The Portland metro carries the long-haul corridors through it, not around it.

    The Wavelengths map draws Portland, Hillsboro and Beaverton as one overlapping
    junction that the corridors run through: the I-5 chain arrives from Salem to the
    south, the Bend/Boise spur leaves to the east, and the Seattle corridor comes down
    from the north. Digitising that junction as a star centred on Portland would leave
    Hillsboro a spur whose only other span is the trans-Pacific cable to Tokyo -- and a
    design needing a route around Portland would then cross the Pacific twice to reach a
    city fifteen miles away. Each metro member therefore keeps its own terrestrial spans.
    """
    assert {("Portland", "OR"), ("Salem", "OR"), ("Beaverton", "OR")} <= _domestic_neighbours(
        ("Hillsboro", "OR")
    )
    assert {("Portland", "OR"), ("Hillsboro", "OR"), ("Bend", "OR")} <= _domestic_neighbours(
        ("Beaverton", "OR")
    )


def test_pacific_gateways_are_not_domestic_spurs() -> None:
    """No trans-Pacific landing city hangs off a single inland hub.

    A gateway with one terrestrial neighbour makes its submarine cable the cheapest way
    around that neighbour, so a resilience detour routes offshore rather than declaring
    the hub a chokepoint. Every Pacific gateway the map lands a cable at is a metro PoP
    with terrestrial fiber of its own, so each has at least two domestic spans.
    """
    pacific = {("Seattle", "WA"), ("Hillsboro", "OR"), ("San Jose", "CA"), ("Los Angeles", "CA")}
    spurs = {city for city in pacific if len(_domestic_neighbours(city)) < 2}
    assert not spurs
