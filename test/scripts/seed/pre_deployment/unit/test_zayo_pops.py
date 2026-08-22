from __future__ import annotations

import csv

from repo_utils import REPO_ROOT

_DATA = REPO_ROOT / "data"
_ZAYO = _DATA / "pops" / "zayo.csv"
_ZAYO_LINKS = [
    _DATA / "fiber_segments" / "terrestrial" / "zayo.csv",
    _DATA / "fiber_segments" / "submarine" / "zayo.csv",
]

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

_GATEWAYS = {
    ("New York", "NY"), ("Ashburn", "VA"), ("Seattle", "WA"), ("Hillsboro", "OR"),
    ("San Jose", "CA"), ("Los Angeles", "CA"), ("Tuckerton", "NJ"),
    ("Manchester", ""), ("London", ""), ("Slough", ""), ("Paris", ""),
    ("Tokyo", ""), ("Hong Kong", ""), ("Singapore", ""), ("Sydney", ""),
    ("Sao Paulo", ""),
}


def _pops() -> list[dict[str, str]]:
    with _ZAYO.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _link_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in _ZAYO_LINKS:
        with path.open(newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def _link_endpoints() -> set[tuple[str, str]]:
    rows = _link_rows()
    near = {(row["A_Municipality"], row["A_State"]) for row in rows}
    return near | {(row["Z_Municipality"], row["Z_State"]) for row in rows}


def _link_pairs() -> set[tuple[tuple[str, str], tuple[str, str]]]:
    return {
        ((row["A_Municipality"], row["A_State"]), (row["Z_Municipality"], row["Z_State"]))
        for row in _link_rows()
    }


def _continent(key: tuple[str, str]) -> str:
    country = {(pop["Municipality"], pop["State"]): pop["Country"] for pop in _pops()}
    return _CONTINENT[country[key]]


def test_city_keys_are_unique() -> None:
    keys = [(pop["Municipality"], pop["State"]) for pop in _pops()]
    assert len(keys) == len(set(keys))


def test_overseas_pops_carry_their_country() -> None:
    located = {(pop["Municipality"], pop["Country"]) for pop in _pops()}
    overseas = {
        ("Tokyo", "Japan"),
        ("London", "United Kingdom"),
        ("Sao Paulo", "Brazil"),
        ("Sydney", "Australia"),
    }
    assert overseas <= located


def test_every_pop_is_connected() -> None:
    keys = {(pop["Municipality"], pop["State"]) for pop in _pops()}
    assert keys <= _link_endpoints()


def test_link_endpoints_resolve_to_pops() -> None:
    keys = {(pop["Municipality"], pop["State"]) for pop in _pops()}
    assert _link_endpoints() <= keys


def test_intercontinental_links_use_submarine_gateways() -> None:
    offenders = {
        (a, z) for a, z in _link_pairs()
        if _continent(a) != _continent(z) and not ({a, z} <= _GATEWAYS)
    }
    assert not offenders


def _domestic_neighbours(city: tuple[str, str]) -> set[tuple[str, str]]:
    country = {(pop["Municipality"], pop["State"]): pop["Country"] for pop in _pops()}
    linked = set()
    for near, far in _link_pairs():
        if near == city:
            linked.add(far)
        elif far == city:
            linked.add(near)
    return {other for other in linked if country.get(other) == "United States"}


def test_pacific_gateways_are_not_domestic_spurs() -> None:
    pacific = {("Seattle", "WA"), ("Hillsboro", "OR"), ("San Jose", "CA"), ("Los Angeles", "CA")}
    spurs = {city for city in pacific if len(_domestic_neighbours(city)) < 2}
    assert not spurs
