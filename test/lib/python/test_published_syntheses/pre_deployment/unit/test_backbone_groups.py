"""Unit tests for the groups the fiber of a published network leaves its backbone seats in.

A WAN is one network or it is not a WAN: an operator handed a synthesis whose seats fall into
two groups can carry no traffic between them, and every other measurement in this module
passes on such a synthesis, because each seat meets its diverse path count against peers inside
its own group (GitHub issue #68).

The helper sweeps the published carrier fiber and hands back the seats group by group. Two
things it must not do are below beside the plain cases: count an access homing as fiber,
since a homing is the haul into the network from a demand site rather than a segment a
backbone path can be laid along, and lose a seat carrying no fiber at all, which is the most
cut off a seat can be.
"""

from __future__ import annotations

from typing import Any

from test_published_syntheses import backbone_groups


def _seat(site_id: str) -> dict[str, Any]:
    """One backbone node of a published collection, as far as this measurement reads it."""
    return {"id": site_id}


def _segment(kind: str, near: str, far: str) -> dict[str, Any]:
    """One link of a published collection, of whichever kind it is labelled with."""
    return {"source_id": near, "target_id": far, "distance_miles": 10.0, "link_kind": kind}


# The fiber of one whole network: west reaches east through the transit city hub.
_JOINED = [
    _segment("carrier_physical", "west", "hub"),
    _segment("carrier_physical", "hub", "east"),
]
# Four seats in two groups: the three above, and salt reaching lake over fiber of its own
# with nothing at all between the two. This is the shape a build must refuse.
_SPLIT: dict[str, Any] = {
    "backbone": [_seat("west"), _seat("east"), _seat("hub"), _seat("salt"), _seat("lake")],
    "links": [*_JOINED, _segment("carrier_physical", "salt", "lake")],
}


def test_a_network_whose_fiber_joins_every_seat_is_one_group() -> None:
    """Three seats on one run of fiber are one network, and come back as one list."""
    assert backbone_groups({"backbone": _SPLIT["backbone"][:3], "links": _JOINED}) == [
        ["east", "hub", "west"]
    ]


def test_seats_the_fiber_leaves_in_two_groups_come_back_as_two_lists() -> None:
    """Each list names the seats stranded together, so the failure says which side is which."""
    assert backbone_groups(_SPLIT) == [["east", "hub", "west"], ["lake", "salt"]]


def test_a_seat_no_fiber_touches_at_all_is_a_group_of_one() -> None:
    """A seat with nothing beside it is the most cut off a seat can be, and is not lost."""
    assert backbone_groups({
        "backbone": [*_SPLIT["backbone"][:3], _seat("alone")],
        "links": _JOINED,
    }) == [["alone"], ["east", "hub", "west"]]


def test_a_seat_reached_only_through_an_access_homing_is_its_own_group() -> None:
    """A homing is the haul into the network from a site, not fiber a backbone path can use."""
    assert backbone_groups({
        "backbone": [*_SPLIT["backbone"][:3], _seat("far")],
        "links": [*_JOINED, _segment("tenant_to_backbone", "east", "far")],
    }) == [["east", "hub", "west"], ["far"]]


def test_a_tenant_with_no_published_backbone_has_no_group() -> None:
    """A build that has not landed publishes no seats, so there is no group to report."""
    assert not backbone_groups({"backbone": [], "links": []})
