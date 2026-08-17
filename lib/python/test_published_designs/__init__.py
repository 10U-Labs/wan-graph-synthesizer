"""Read a published WAN from the API and measure it the way an outside reader would.

The delivered-design layer reads what the deployed synthesizer published and judges it.
This module is both halves of that job: the reader that asks the service for a tenant's
network and for the state of its build, and the four measurements that cannot be answered
by reading a number back -- what the worst haul of a published network really is, whether
any published link wanders further from the straight line than its tenant allows, whether
any of them wanders further than the fiber it was routed over made necessary, and whether
any pair of sites was drawn with more routes between them than the tenant bought.

The reading goes through the API and not through the S3 bucket the synthesizer writes to.
The bucket holds only what the synthesizer chose to publish, which is three of the eight
settings a tenant's ``backbone`` block declares, so a reader there has to guess whether
the network in front of it was built to the config git now holds and is wrong about the
other five. ``GET tenants/{tenant}/wan`` answers that outright: it reports the state of the
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

import heapq
import json
import math
from typing import Any
from urllib.error import HTTPError

from seed import _get
from synthesizer.input_graph import Vertex, haversine_miles

# How far a fiber route wanders past the straight line between its two ends. Route miles
# run somewhere between one and two air miles on real terrestrial builds, so a published
# link measured against the great-circle distance is allowed twice its tenant's bound.
SINUOSITY = 2.0

# Miles of slack absorbing the rounding in the published numbers. Every distance is served
# to three decimal places, so a route summed span by span can differ from the one the
# synthesizer measured by a thousandth of a mile a span; a tenth of a mile covers a route
# of a hundred spans and is far too little to admit a detour.
ROUNDING_SLACK = 0.1

# The label the published edges collection gives a span of carrier fiber, as opposed to
# the access homings served alongside it (see ``synthesizer.output.design_payload``).
FIBER = "carrier_physical"

# The states the service reports while it is still deciding what a tenant's network is.
# The POST that starts a build records ``creating`` before it answers, and the synthesizer
# records ``building`` when it picks the work up, so a tenant in neither state has a
# network that is finished -- published, or failed and reported as failed.
UNFINISHED = frozenset({"creating", "building"})

# The published collections this module reads, under the names the API serves them by.
COLLECTIONS = ("backbone-nodes", "backbone-links", "tenant-nodes", "provider-nodes", "edges")


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
        "max_backup_route_multiple": backbone["max_backup_route_multiple"],
        "number_of_diverse_paths": backbone["number_of_diverse_paths"],
        "seat_cap": backbone["node_count"]["max"],
        "forced": backbone.get("forced", {}).get("nodes", []),
        "status": state,
        "backbone": published.get("backbone-nodes", []),
        "demand": published.get("tenant-nodes", []) + published.get("provider-nodes", []),
        "links": published.get("backbone-links", []),
        "edges": published.get("edges", []),
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
    allowed = SINUOSITY * design["max_backup_route_multiple"]
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


def overbuilt_pairs(design: dict[str, Any]) -> list[tuple[str, int]]:
    """Every pair of backbone sites drawn with more routes than the tenant asked for.

    A tenant's number of diverse paths is how many routes it is buying between two of its
    sites, so a pair carrying more than that is carrying cable nobody ordered. Reported as
    the pair and the routes it holds, which is what names the overbuild to whoever reads
    the failure.

    Counting a pair rather than measuring one route is the whole point of asking this from
    out here. Every route can be inside the backup route multiple and be the shortest way
    over its own fiber -- which is what :func:`overrun_links` and :func:`detoured_links`
    ask -- while there are simply too many of them. Two-Node was published with five routes
    between Ashburn, VA and Salt Lake City, UT, all five of them individually sound, and no
    published measurement had anything to say about it (GitHub issue #58).

    The two ends are ordered before they are counted, so a pair served under either name is
    the one pair it is.
    """
    drawn: dict[tuple[str, str], int] = {}
    for link in design["links"]:
        pair = tuple(sorted((link["source_id"], link["target_id"])))
        drawn[pair] = drawn.get(pair, 0) + 1
    allowed = design["number_of_diverse_paths"]
    return [
        (" <-> ".join(pair), count)
        for pair, count in sorted(drawn.items())
        if count > allowed
    ]


def _published_fiber(design: dict[str, Any]) -> dict[str, dict[str, float]]:
    """The carrier fiber a published network was routed over, span by span between sites.

    The access homings served in the same collection are left out. A homing joins a demand
    site to the backbone node it is served from rather than joining fiber to fiber, so a
    route counted through one would be two hauls read as a span, and it would shorten the
    way between two backbone nodes by cable no link could be laid along.
    """
    fiber: dict[str, dict[str, float]] = {}
    for edge in design["edges"]:
        if edge["edge_kind"] != FIBER:
            continue
        fiber.setdefault(edge["source_id"], {})[edge["target_id"]] = edge["distance_miles"]
        fiber.setdefault(edge["target_id"], {})[edge["source_id"]] = edge["distance_miles"]
    return fiber


def _shortest_fiber_miles(
    fiber: dict[str, dict[str, float]], source: str, target: str
) -> float:
    """The least cable joining two sites over ``fiber``, or infinity where none does.

    Infinity rather than an error, because a pair the published fiber does not join is a
    pair with no shortest route to compare a link against, and the caller has nothing to
    say about it.
    """
    known: set[str] = set()
    queue: list[tuple[float, str]] = [(0.0, source)]
    while queue:
        run, city = heapq.heappop(queue)
        if city == target:
            return run
        if city in known:
            continue
        known.add(city)
        for neighbor, miles in fiber.get(city, {}).items():
            if neighbor not in known:
                heapq.heappush(queue, (run + miles, neighbor))
    return math.inf


def detoured_links(design: dict[str, Any]) -> list[tuple[str, float]]:
    """Every published backbone link routed further than its own fiber made necessary.

    Each link is measured against the shortest way over the carrier fiber the published
    network itself carries, which is the strongest statement about a routed link that can
    be made from outside the build: an operator reading the collections can see the spans
    the design ordered, so they can see whether a link joining two sites took the cheapest
    of them or wandered.

    It is a bound on each link on its own, and not the question the proof answers. What the
    proof chooses is a *set* of routes out of one site that no city's loss takes two of, and
    the shortest such set can hold a route longer than that pair's own shortest -- the
    second way out has to avoid the first. So a set of needlessly long routes can pass here
    while every link in it is inside the bound (GitHub issue #57). The unit and integration
    tiers are what ask the sharper question; this catches the single link that wanders, and
    needs nothing added to what is published to do it.

    Sound whichever way the published fiber is short of the carrier's. The denominator is
    the shortest route over the spans the design ordered, which is never shorter than the
    shortest route over all the fiber the synthesizer had, so a link the synthesizer's own
    bound allowed is allowed here too.
    """
    fiber = _published_fiber(design)
    allowed = design["max_backup_route_multiple"]
    detoured = []
    for link in design["links"]:
        shortest = _shortest_fiber_miles(fiber, link["source_id"], link["target_id"])
        if shortest > 0 and link["distance_miles"] > allowed * shortest + ROUNDING_SLACK:
            detoured.append((" -> ".join(link["path"]), link["distance_miles"] / shortest))
    return detoured
