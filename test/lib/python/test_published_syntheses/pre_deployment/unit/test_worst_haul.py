"""Unit tests for the worst haul a published network leaves the sites its target covers.

The number this helper computes is the whole of what
``test_the_reported_worst_haul_is_the_one_the_published_network_delivers`` asserts on, so
a synthesis is built here whose answer is known from the geometry rather than from the
helper: two backbone nodes on one meridian and every site on that meridian too, which
makes each haul a whole number of degrees of latitude. A degree of latitude is 69.09 miles
on the globe the synthesizer measures over, so the answers below are multiples of it.
"""

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
    """A published demand site on the two backbone nodes' meridian."""
    return {
        "id": name,
        "name": name,
        "kind": "site",
        "coords": [latitude, -100.0],
        "exempt_from_distance_constraint": exempt,
    }


def _synthesis(*demand: dict[str, Any]) -> dict[str, Any]:
    """A published network of both backbone nodes carrying the given demand."""
    return {"backbone": [_SOUTH, _NORTH], "demand": list(demand)}


def test_the_worst_haul_is_the_farthest_site_from_the_node_nearest_it() -> None:
    """The site three degrees from one node and two from the other is measured at two.

    So the answer is 138.2 miles rather than the 207.3 a measure taken to the wrong node
    would give, and rather than the 2,073 the exempt site would contribute were the
    operator's exemption not honoured here as it is in the synthesizer's own stop
    condition. The nearer site, one degree out, is the one the maximum has to pass over.
    """
    synthesis = _synthesis(
        _site("near", 41.0, False), _site("far", 43.0, False), _site("oconus", 10.0, True)
    )
    assert worst_haul(synthesis) == 138.2


def test_a_synthesis_whose_every_site_is_exempt_reads_zero() -> None:
    """A network the distance constraint reaches no site of has no worst haul to report.

    Zero rather than an error on an empty sequence, which is the answer the synthesizer's
    own ``coverage_worst_haul`` gives for the same synthesis and the branch a live network
    would only reach if an operator exempted every site it has.
    """
    assert worst_haul(_synthesis(_site("oconus", 10.0, True))) == 0.0
