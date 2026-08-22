from __future__ import annotations

from typing import Any

from test_published_syntheses import backbone_groups


def _seat(site_id: str) -> dict[str, Any]:
    return {"id": site_id}


def _segment(kind: str, near: str, far: str) -> dict[str, Any]:
    return {"source_id": near, "target_id": far, "distance_miles": 10.0, "link_kind": kind}


_JOINED = [
    _segment("carrier_physical", "west", "hub"),
    _segment("carrier_physical", "hub", "east"),
]
_SPLIT: dict[str, Any] = {
    "backbone": [_seat("west"), _seat("east"), _seat("hub"), _seat("salt"), _seat("lake")],
    "paths": [*_JOINED, _segment("carrier_physical", "salt", "lake")],
}


def test_a_network_whose_fiber_joins_every_seat_is_one_group() -> None:
    assert backbone_groups({"backbone": _SPLIT["backbone"][:3], "paths": _JOINED}) == [
        ["east", "hub", "west"]
    ]


def test_seats_the_fiber_leaves_in_two_groups_come_back_as_two_lists() -> None:
    assert backbone_groups(_SPLIT) == [["east", "hub", "west"], ["lake", "salt"]]


def test_a_seat_no_fiber_touches_at_all_is_a_group_of_one() -> None:
    assert backbone_groups({
        "backbone": [*_SPLIT["backbone"][:3], _seat("alone")],
        "paths": _JOINED,
    }) == [["alone"], ["east", "hub", "west"]]


def test_a_seat_reached_only_through_an_access_homing_is_its_own_group() -> None:
    assert backbone_groups({
        "backbone": [*_SPLIT["backbone"][:3], _seat("far")],
        "paths": [*_JOINED, _segment("tenant_to_backbone", "east", "far")],
    }) == [["east", "hub", "west"], ["far"]]


def test_a_tenant_with_no_published_backbone_has_no_group() -> None:
    assert not backbone_groups({"backbone": [], "paths": []})
