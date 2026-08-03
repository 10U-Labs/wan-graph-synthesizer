"""Measure a published WAN the way a reader outside the synthesizer would measure it.

The delivered-design layer reads what the deployed synthesizer published and judges it.
Two of its questions cannot be answered by reading a number back -- what the worst haul
of a published network really is, and whether any published link wanders further from the
straight line than its tenant allows -- so both are recomputed here from the published
collections alone.

The recomputation deliberately does not go through ``synthesizer.coverage``. The report
being judged is what that module produced, so measuring with it would only establish that
it agrees with itself. Only ``haversine_miles`` is borrowed, since the distance between
two points on the globe is not the thing in question.

That is also why this lives here rather than beside the assertions it serves. A helper
that computes the number an assertion rests on is the whole of the measurement, and one
reachable only from a tier that needs a deployment and AWS credentials is graded by the
system it exists to grade. Here a unit tier can hold it to literal inputs, including the
cases a healthy network never produces (GitHub issue #50).
"""

from __future__ import annotations

from typing import Any

from synthesizer.input_graph import Vertex, haversine_miles

# How far a fiber route wanders past the straight line between its two ends. Route miles
# run somewhere between one and two air miles on real terrestrial builds, so a published
# link measured against the great-circle distance is allowed twice its tenant's bound.
SINUOSITY = 2.0


def vertex(node: dict[str, Any]) -> Vertex:
    """Rebuild a published node as the vertex type the distance helper takes."""
    latitude, longitude = node["coords"]
    return Vertex(node["id"], node["name"], node["kind"], (latitude, longitude))


def worst_haul(design: dict[str, Any]) -> float:
    """The farthest any site the target applies to sits from its nearest backbone node.

    Sites the operator has excused the distance constraint are left out, as they are in the
    synthesizer's own stop condition, and a design carrying no demand at all reads zero.
    """
    nodes = [vertex(node) for node in design["backbone"]]
    hauls: list[float] = [
        min(haversine_miles(vertex(site), node) for node in nodes)
        for site in design["demand"]
        if not site["exempt_from_distance_constraint"]
    ]
    return round(max(hauls, default=0.0), 1)


def overrun_links(design: dict[str, Any]) -> list[tuple[str, float]]:
    """Every published backbone link routed further than even a generous bound allows.

    A link is skipped rather than judged when it names a node the published backbone does
    not hold, when its two ends resolve to the same node, or when its ends sit at one set
    of coordinates: none of the three leaves a direct distance to measure a ratio against.
    A published network contains no such link, which is why the unit tier owns those three
    branches -- each of them discards a link and says nothing, and a helper discarding
    every link returns the empty list a sound network returns.
    """
    coords = {node["id"]: vertex(node) for node in design["backbone"]}
    allowed = SINUOSITY * design["max_path_stretch"]
    overrun = []
    for link in design["links"]:
        source = coords.get(link["source_id"])
        target = coords.get(link["target_id"])
        if source is None or target is None or source is target:
            continue
        direct = haversine_miles(source, target)
        if direct > 0 and link["distance_miles"] > allowed * direct:
            overrun.append((" -> ".join(link["path"]), link["distance_miles"] / direct))
    return overrun
