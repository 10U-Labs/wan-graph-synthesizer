from __future__ import annotations

from typing import Any

from test_published_syntheses import worst_haul

_SOUTH: dict[str, Any] = {
    "id": "south", "name": "South", "kind": "PoP", "coords": [40.0, -100.0],
}
_NORTH: dict[str, Any] = {
    "id": "north", "name": "North", "kind": "PoP", "coords": [45.0, -100.0],
}


def _site(name: str, latitude: float, exempt: bool) -> dict[str, Any]:
    return {
        "id": name,
        "name": name,
        "kind": "site",
        "coords": [latitude, -100.0],
        "exempt_from_distance_constraint": exempt,
    }


def _synthesis(*demand: dict[str, Any]) -> dict[str, Any]:
    return {"backbone": [_SOUTH, _NORTH], "demand": list(demand)}


def test_the_worst_haul_is_the_farthest_site_from_the_node_nearest_it() -> None:
    synthesis = _synthesis(
        _site("near", 41.0, False), _site("far", 43.0, False), _site("oconus", 10.0, True)
    )
    assert worst_haul(synthesis) == 138.2


def test_a_synthesis_whose_every_site_is_exempt_reads_zero() -> None:
    assert worst_haul(_synthesis(_site("oconus", 10.0, True))) == 0.0
