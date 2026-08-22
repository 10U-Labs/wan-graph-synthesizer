from __future__ import annotations

from typing import Any

from test_published_syntheses import overrun_links

_WEST: dict[str, Any] = {
    "id": "west", "name": "West", "kind": "PoP", "coords": [40.0, -100.0],
}
_EAST: dict[str, Any] = {
    "id": "east", "name": "East", "kind": "PoP", "coords": [40.0, -99.0],
}
_ANNEX: dict[str, Any] = {
    "id": "annex", "name": "Annex", "kind": "PoP", "coords": [40.0, -100.0],
}


def _synthesis(source: str, target: str, distance: float) -> dict[str, Any]:
    return {
        "backbone": [_WEST, _EAST, _ANNEX],
        "links": [{
            "source_id": source,
            "target_id": target,
            "distance_miles": distance,
            "path": [source, target],
        }],
        "max_backup_path_multiple": 3.0,
    }


def test_a_link_drawn_past_the_bound_is_reported_by_the_path_it_takes() -> None:
    assert [path for path, _ in overrun_links(_synthesis("west", "east", 1000.0))] == [
        "west -> east"
    ]


def test_a_link_inside_the_bound_is_left_alone() -> None:
    assert not overrun_links(_synthesis("west", "east", 100.0))


def test_a_link_whose_two_ends_are_the_same_node_is_discarded() -> None:
    assert not overrun_links(_synthesis("west", "west", 1000.0))


def test_a_link_naming_a_node_outside_the_backbone_is_discarded() -> None:
    assert not overrun_links(_synthesis("west", "ghost", 1000.0))


def test_a_link_between_two_nodes_at_one_place_is_discarded() -> None:
    assert not overrun_links(_synthesis("west", "annex", 1000.0))
