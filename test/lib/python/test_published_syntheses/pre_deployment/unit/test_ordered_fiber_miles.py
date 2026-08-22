from __future__ import annotations

from typing import Any

from test_published_syntheses import ordered_fiber_miles


def _segment(kind: str, near: str, far: str, miles: float) -> dict[str, Any]:
    return {"source_id": near, "target_id": far, "distance_miles": miles, "link_kind": kind}


_ORDERED: list[dict[str, Any]] = [
    _segment("carrier_physical", "west", "hub", 120.5),
    _segment("carrier_physical", "hub", "east", 240.25),
    _segment("tenant_to_backbone", "site", "west", 4.0),
    _segment("provider_to_backbone", "region", "east", 9.0),
]


def test_the_miles_ordered_are_the_carrier_fiber_the_network_runs_over() -> None:
    assert ordered_fiber_miles({"paths": _ORDERED}) == 360.75


def test_a_network_whose_links_are_all_homings_ordered_no_fiber() -> None:
    assert ordered_fiber_miles({"paths": _ORDERED[2:]}) == 0


def test_a_network_carrying_no_links_ordered_no_fiber() -> None:
    assert ordered_fiber_miles({"paths": []}) == 0
