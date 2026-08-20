"""Unit tests for the miles of carrier fiber a published network ordered.

The helper adds up the fiber a published synthesis runs over, which is the size of the network
in the only unit anything here is measured in and the figure the floor a build publishes
under itself is held against: a synthesis running more than twice the fewest miles that could
meet its tenant's requirements has lost the guarantee its own build claims (GitHub issue
#60).

What it must not add up is the access homings the published links collection carries beside
the fiber. A homing joins a demand site to the backbone node it is served from, so its
miles are the haul into the network rather than fiber between backbone sites, and counting
them would inflate every synthesis by every site homed into it. Both kinds are below, under the
two labels the synthesizer publishes homings by and the one it publishes fiber by.
"""

from __future__ import annotations

from typing import Any

from test_published_syntheses import ordered_fiber_miles


def _segment(kind: str, near: str, far: str, miles: float) -> dict[str, Any]:
    """One link of a published collection, of whichever kind it is labelled with."""
    return {"source_id": near, "target_id": far, "distance_miles": miles, "link_kind": kind}


# Two segments of carrier fiber, 360.75 miles of it, and the two homings that are not fiber:
# a tenant site into west and a provider region into east.
_ORDERED: list[dict[str, Any]] = [
    _segment("carrier_physical", "west", "hub", 120.5),
    _segment("carrier_physical", "hub", "east", 240.25),
    _segment("tenant_to_backbone", "site", "west", 4.0),
    _segment("provider_to_backbone", "region", "east", 9.0),
]


def test_the_miles_ordered_are_the_carrier_fiber_the_network_runs_over() -> None:
    """The two fiber segments add up to 360.75, and the thirteen miles of homing are left out."""
    assert ordered_fiber_miles({"links": _ORDERED}) == 360.75


def test_a_network_whose_links_are_all_homings_ordered_no_fiber() -> None:
    """Sites homed into a backbone that holds no fiber of its own is no fiber ordered.

    A reader adding up every link served would call this thirteen miles of network, which
    is thirteen miles nobody laid.
    """
    assert ordered_fiber_miles({"links": _ORDERED[2:]}) == 0


def test_a_network_carrying_no_links_ordered_no_fiber() -> None:
    """A tenant whose build has not landed published no fiber and reads as none."""
    assert ordered_fiber_miles({"links": []}) == 0
