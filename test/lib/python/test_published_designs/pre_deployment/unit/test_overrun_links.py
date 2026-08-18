"""Unit tests for the published links drawn further than their tenant's bound allows.

Three of the four cases below are links the helper discards without recording that it
did, and no published network will ever contain one: a real design names no node outside
its own backbone, joins no node to itself, and seats no two nodes at one set of
coordinates. They are tested here because a helper that discarded every link would return
the empty list a sound network returns, and the assertion that stands on it could not tell
the two apart.

The two nodes sit a degree of longitude apart at forty degrees north, which is 52.9 miles
of great circle, and the tenant allows three times the direct distance. The sinuosity
allowance doubles that, so a link between them is over-long past 317 miles.
"""

from __future__ import annotations

from typing import Any

from test_published_designs import overrun_links

_WEST: dict[str, Any] = {
    "id": "west", "name": "West", "kind": "PoP", "coords": [40.0, -100.0],
}
_EAST: dict[str, Any] = {
    "id": "east", "name": "East", "kind": "PoP", "coords": [40.0, -99.0],
}
# A third node at the western node's own coordinates, so the two are distinct nodes with
# no distance between them.
_ANNEX: dict[str, Any] = {
    "id": "annex", "name": "Annex", "kind": "PoP", "coords": [40.0, -100.0],
}


def _design(source: str, target: str, distance: float) -> dict[str, Any]:
    """A published network of the three nodes carrying one drawn link between two ids."""
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
    """A thousand miles of path between two cities 52.9 miles apart is nineteen times out.

    Reported by its path, which is what names the detour to whoever reads the failure:
    the paths GitHub issue #44 produced ran through Paris and through Tokyo.
    """
    assert [path for path, _ in overrun_links(_design("west", "east", 1000.0))] == [
        "west -> east"
    ]


def test_a_link_inside_the_bound_is_left_alone() -> None:
    """Twice the direct distance is ordinary terrestrial fiber, not a detour."""
    assert not overrun_links(_design("west", "east", 100.0))


def test_a_link_whose_two_ends_are_the_same_node_is_discarded() -> None:
    """A node joined to itself has no direct distance to be measured against."""
    assert not overrun_links(_design("west", "west", 1000.0))


def test_a_link_naming_a_node_outside_the_backbone_is_discarded() -> None:
    """An endpoint the published backbone does not hold cannot be placed on the globe."""
    assert not overrun_links(_design("west", "ghost", 1000.0))


def test_a_link_between_two_nodes_at_one_place_is_discarded() -> None:
    """Zero direct distance makes every ratio infinite, so the bound says nothing."""
    assert not overrun_links(_design("west", "annex", 1000.0))
