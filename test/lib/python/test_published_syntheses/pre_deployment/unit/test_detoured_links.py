from __future__ import annotations

from typing import Any

from test_published_syntheses import detoured_links

_LINKS: list[dict[str, Any]] = [
    {"source_id": "west", "target_id": "hub", "distance_miles": 10.0,
     "link_kind": "carrier_physical"},
    {"source_id": "hub", "target_id": "east", "distance_miles": 10.0,
     "link_kind": "carrier_physical"},
    {"source_id": "west", "target_id": "east", "distance_miles": 100.0,
     "link_kind": "carrier_physical"},
    {"source_id": "site", "target_id": "west", "distance_miles": 1.0,
     "link_kind": "tenant_to_backbone"},
    {"source_id": "site", "target_id": "east", "distance_miles": 1.0,
     "link_kind": "tenant_to_backbone"},
]


def _synthesis(source: str, target: str, distance: float) -> dict[str, Any]:
    return {
        "paths": _LINKS,
        "max_backup_path_multiple": 3.0,
        "links": [
            {
                "source_id": source,
                "target_id": target,
                "distance_miles": distance,
                "path": [source, target],
            }
        ],
    }


def test_a_link_drawn_past_the_bound_is_reported_by_the_path_it_takes() -> None:
    assert [path for path, _ in detoured_links(_synthesis("west", "east", 1000.0))] == [
        "west -> east"
    ]


def test_a_link_is_not_measured_against_a_path_through_an_access_homing() -> None:
    assert not detoured_links(_synthesis("west", "east", 40.0))


def test_a_link_whose_two_ends_are_the_same_site_is_discarded() -> None:
    assert not detoured_links(_synthesis("west", "west", 1000.0))


def test_a_link_naming_a_site_the_published_fiber_does_not_reach_is_discarded() -> None:
    assert not detoured_links(_synthesis("west", "ghost", 1000.0))
