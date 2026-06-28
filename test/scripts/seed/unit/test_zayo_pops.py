"""Data-integrity checks for the worldwide Zayo IP PoP vertex list.

The Zayo carrier vertices are merged from the mapbook's text IP PoP List, so they
now span the globe. These guard the two invariants that the merge must preserve:
every PoP is keyed by a distinct ``(municipality, state)`` and the overseas PoPs
carry their country.
"""

from __future__ import annotations

import csv

from repo_utils import REPO_ROOT

_ZAYO = REPO_ROOT / "data" / "vertices" / "carriers" / "zayo.csv"


def _pops() -> list[dict[str, str]]:
    """The Zayo vertex rows."""
    with _ZAYO.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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
