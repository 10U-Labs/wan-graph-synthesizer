from __future__ import annotations

from typing import Any

from test_published_syntheses import cut_cities


def _published_paths(crossings: list[tuple[str, ...]]) -> list[dict[str, Any]]:
    return [{"path": list(cities)} for cities in crossings]


_RING = _published_paths([
    ("west", "a", "north"),
    ("north", "b", "east"),
    ("east", "d", "south"),
    ("south", "f", "west"),
])

_BOWTIE = _published_paths([
    ("west", "a", "waist"),
    ("waist", "b", "west"),
    ("east", "c", "waist"),
    ("waist", "d", "east"),
])

_CHAIN = _published_paths([("west", "middle", "centre", "east")])

_APART = _published_paths([("west", "a", "north"), ("east", "b", "south")])


def test_a_network_no_city_carries_names_nobody() -> None:
    assert cut_cities(_RING) == []


def test_a_network_one_city_holds_together_names_that_city() -> None:
    assert cut_cities(_BOWTIE) == ["waist"]


def test_a_network_two_cities_hold_together_names_both_of_them() -> None:
    assert cut_cities(_CHAIN) == ["centre", "middle"]


def test_a_network_that_is_already_in_pieces_names_nobody() -> None:
    assert cut_cities(_APART) == []
