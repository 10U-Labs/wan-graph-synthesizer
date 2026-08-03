"""Read a published WAN from the API and measure it the way an outside reader would.

The delivered-design layer reads what the deployed synthesizer published and judges it.
This module is both halves of that job: the reader that asks the service for a tenant's
network and for the state of its build, and the two measurements that cannot be answered
by reading a number back -- what the worst haul of a published network really is, and
whether any published link wanders further from the straight line than its tenant allows.

The reading goes through the API and not through the S3 bucket the synthesizer writes to.
The bucket holds only what the synthesizer chose to publish, which is two of the eight
settings a tenant's ``backbone`` block declares, so a reader there has to guess whether
the network in front of it was built to the config git now holds and is wrong about the
other six. ``GET tenants/{tenant}/wan`` answers that outright: it reports the state of the
build rather than the requirements the build ran under, and the build is started by the
seed run that delivered those requirements (GitHub issue #47).

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

import json
from typing import Any
from urllib.error import HTTPError

from seed import _get
from synthesizer.input_graph import Vertex, haversine_miles

# How far a fiber route wanders past the straight line between its two ends. Route miles
# run somewhere between one and two air miles on real terrestrial builds, so a published
# link measured against the great-circle distance is allowed twice its tenant's bound.
SINUOSITY = 2.0

# The states the service reports while it is still deciding what a tenant's network is.
# The POST that starts a build records ``creating`` before it answers, and the synthesizer
# records ``building`` when it picks the work up, so a tenant in neither state has a
# network that is finished -- published, or failed and reported as failed.
UNFINISHED = frozenset({"creating", "building"})

# The published collections this module reads, under the names the API serves them by.
COLLECTIONS = ("backbone-nodes", "backbone-links", "tenant-nodes", "provider-nodes")


def request_paths(tenant: str) -> list[str]:
    """Every API path a tenant's published network is read from, the build state first.

    Every request this module makes is one of these, so what the service is asked for can
    be held against ``src/www/api/openapi.json`` without a deployment to ask.
    """
    return [f"tenants/{tenant}/{name}" for name in ("wan", *COLLECTIONS)]


def _build_state(api: str, path: str) -> dict[str, Any]:
    """The document the service serves for a tenant's build, whatever it says.

    ``GET tenants/{tenant}/wan`` answers 422 for a build that failed and 404 for a tenant
    nothing has ever been built for, and urllib raises on both. Each answer is still a
    document saying which case it is, so the body is read back rather than the error
    re-raised: a build that failed is something this layer reports on, one tenant at a
    time, rather than something every test in the layer dies of inside a fixture.
    """
    try:
        state: dict[str, Any] = _get(api, path)
    except HTTPError as refusal:
        state = json.loads(refusal.read())
    return state


def published_design(api: str, tenant: str, config: dict[str, Any]) -> dict[str, Any]:
    """One tenant's published network beside the demands its own config makes of it.

    A tenant whose build has not finished has no network to read, so its collections come
    back empty rather than fetched: the collection endpoints answer 404 until the first
    build lands, and the first test in the layer is the one that reports the tenant.
    """
    state_path, *collection_paths = request_paths(tenant)
    state = _build_state(api, state_path)
    published: dict[str, Any] = (
        {path.rsplit("/", 1)[-1]: _get(api, path) for path in collection_paths}
        if state.get("status") == "ready" else {}
    )
    backbone = config["backbone"]
    return {
        "tenant": tenant,
        "target_miles": backbone["coverage_target_miles"],
        "max_path_stretch": backbone["max_path_stretch"],
        "seat_cap": backbone["node_count"]["max"],
        "forced": backbone.get("forced", {}).get("nodes", []),
        "status": state,
        "backbone": published.get("backbone-nodes", []),
        "demand": published.get("tenant-nodes", []) + published.get("provider-nodes", []),
        "links": published.get("backbone-links", []),
    }


def settled(status: dict[str, Any]) -> bool:
    """True once the service has finished deciding what a tenant's network is.

    A reader that arrives while a build is running would measure a network the operator
    has already replaced, so it waits. What it waits for is the build itself and nothing
    else: the state moves out of ``creating`` and ``building`` exactly once per build, and
    the build was started by the seed run that delivered the config it was built from.
    Nothing here enumerates the settings a tenant declares, so a setting added to ``etc/``
    tomorrow cannot leave this reading a network built before it existed.
    """
    return status.get("status") not in UNFINISHED


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
