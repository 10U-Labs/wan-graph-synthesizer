from __future__ import annotations

import json
from collections import deque
from itertools import combinations
from typing import Any
from urllib.error import HTTPError

from seed import _get
from synthesizer.input_graph import Site, haversine_miles


FIBER = "carrier_physical"

UNFINISHED = frozenset({"creating", "synthesizing"})

COLLECTIONS = ("backbone-nodes", "backbone-links", "tenant-nodes", "provider-nodes", "paths")


def request_paths(tenant: str) -> list[str]:
    return [f"tenants/{tenant}/{name}" for name in ("wan", *COLLECTIONS)]


def _build_state(api: str, path: str) -> dict[str, Any]:
    try:
        state: dict[str, Any] = _get(api, path)
    except HTTPError as refusal:
        state = json.loads(refusal.read())
    return state


def published_synthesis(api: str, tenant: str, config: dict[str, Any]) -> dict[str, Any]:
    state_path, *collection_paths = request_paths(tenant)
    state = _build_state(api, state_path)
    published: dict[str, Any] = (
        {path.rsplit("/", 1)[-1]: _get(api, path) for path in collection_paths}
        if state.get("status") == "success" else {}
    )
    backbone = config["backbone"]
    return {
        "tenant": tenant,
        "target_miles": backbone["coverage_target_miles"],
        "number_of_diverse_paths": backbone["number_of_diverse_paths"],
        "seat_cap": backbone["node_count"]["max"],
        "forced": backbone.get("forced", {}).get("nodes", []),
        "forced_paths": backbone.get("forced", {}).get("paths", []),
        "status": state,
        "lower_bound_miles": state.get("backbone_lower_bound_miles"),
        "backbone": published.get("backbone-nodes", []),
        "demand": published.get("tenant-nodes", []) + published.get("provider-nodes", []),
        "links": published.get("backbone-links", []),
        "paths": published.get("paths", []),
    }


def settled(status: dict[str, Any]) -> bool:
    return status.get("status") not in UNFINISHED


def site_from_node(node: dict[str, Any]) -> Site:
    latitude, longitude = node["coords"]
    return Site(node["id"], node["name"], node["kind"], (latitude, longitude))


def worst_haul(synthesis: dict[str, Any]) -> float:
    nodes = [site_from_node(node) for node in synthesis["backbone"]]
    hauls: list[float] = [
        min(haversine_miles(site_from_node(site), node) for node in nodes)
        for site in synthesis["demand"]
        if not site["exempt_from_distance_constraint"]
    ]
    return round(max(hauls, default=0.0), 1)


def _ways_out(
    links: list[dict[str, Any]], site: str, names: dict[str, str]
) -> list[tuple[str, frozenset[str]]]:
    return [
        (
            names[link["target_id"] if link["source_id"] == site else link["source_id"]],
            frozenset(link["path"]) - {names[site]},
        )
        for link in links
        if site in (link["source_id"], link["target_id"])
    ]


def _fail_apart(ways: tuple[tuple[str, frozenset[str]], ...]) -> bool:
    return all(
        not ((near & far) - ({peer} if peer == other else frozenset()))
        for (peer, near), (other, far) in combinations(ways, 2)
    )


def independent_ways_out(
    links: list[dict[str, Any]], site: str, names: dict[str, str]
) -> int:
    ways = _ways_out(links, site, names)
    return max(
        (
            size
            for size in range(1, len(ways) + 1)
            if any(_fail_apart(combo) for combo in combinations(ways, size))
        ),
        default=0,
    )


def overbuilt_pairs(synthesis: dict[str, Any]) -> list[tuple[str, int]]:
    drawn: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for link in synthesis["links"]:
        pair = tuple(sorted((link["source_id"], link["target_id"])))
        drawn.setdefault(pair, []).append(link)
    names = {node["id"]: node["name"] for node in synthesis["backbone"]}
    asked = synthesis["number_of_diverse_paths"]
    overbuilt: list[tuple[str, int]] = []
    for pair, paths in sorted(drawn.items()):
        if len(paths) < 2:
            continue
        spare = max(paths, key=lambda path: path["distance_miles"])
        kept = [link for link in synthesis["links"] if link is not spare]
        if not any(
            independent_ways_out(kept, end, names)
            < min(asked, independent_ways_out(synthesis["links"], end, names))
            for end in pair
        ):
            overbuilt.append((" <-> ".join(pair), len(paths)))
    return overbuilt


def _joined_to(pairs: list[tuple[str, str]]) -> dict[str, set[str]]:
    joined: dict[str, set[str]] = {}
    for near, far in pairs:
        joined.setdefault(near, set()).add(far)
        joined.setdefault(far, set()).add(near)
    return joined


def _reached(joined: dict[str, set[str]], start: str) -> set[str]:
    found = {start}
    unswept = [start]
    while unswept:
        here = unswept.pop()
        for there in joined[here] - found:
            found.add(there)
            unswept.append(there)
    return found


def _all_one_network(joined: dict[str, set[str]]) -> bool:
    return all(_reached(joined, start) == set(joined) for start in sorted(joined)[:1])


def cut_cities(links: list[dict[str, Any]]) -> list[str]:
    joined = _cities_the_paths_cross(links)
    if not _all_one_network(joined):
        return []
    return sorted(
        lost
        for lost in joined
        if not _all_one_network({
            city: reached - {lost} for city, reached in joined.items() if city != lost
        })
    )


def _sites_the_paths_join(
    links: list[dict[str, Any]], sites: list[str]
) -> dict[str, set[str]]:
    alone: dict[str, set[str]] = {site: set() for site in sites}
    return alone | _joined_to([(link["source_id"], link["target_id"]) for link in links])


def _cities_the_paths_cross(links: list[dict[str, Any]]) -> dict[str, set[str]]:
    return _joined_to([
        (near, far)
        for link in links
        for near, far in zip(link["path"], link["path"][1:])
    ])


def removable_paths(synthesis: dict[str, Any]) -> list[tuple[str, float]]:
    names = {node["id"]: node["name"] for node in synthesis["backbone"]}
    sites = list(names)
    asked = synthesis["number_of_diverse_paths"]
    pinned = {
        frozenset((pair["source"], pair["target"])) for pair in synthesis["forced_paths"]
    }
    held_ways_out = {
        site: min(asked, independent_ways_out(synthesis["links"], site, names))
        for site in sites
    }
    survives_a_city_loss = not cut_cities(synthesis["links"])
    removable: list[tuple[str, float]] = []
    for spare in synthesis["links"]:
        if frozenset((names[spare["source_id"]], names[spare["target_id"]])) in pinned:
            continue
        kept = [link for link in synthesis["links"] if link is not spare]
        if any(
            independent_ways_out(kept, site, names) < held_ways_out[site] for site in sites
        ):
            continue
        if not _all_one_network(_sites_the_paths_join(kept, sites)):
            continue
        if survives_a_city_loss and cut_cities(kept):
            continue
        removable.append((" -> ".join(spare["path"]), spare["distance_miles"]))
    return sorted(removable, key=lambda found: (-found[1], found[0]))


def _published_fiber(synthesis: dict[str, Any]) -> dict[str, dict[str, float]]:
    fiber: dict[str, dict[str, float]] = {}
    for link in synthesis["paths"]:
        if link["link_kind"] != FIBER:
            continue
        fiber.setdefault(link["source_id"], {})[link["target_id"]] = link["distance_miles"]
        fiber.setdefault(link["target_id"], {})[link["source_id"]] = link["distance_miles"]
    return fiber


def backbone_groups(synthesis: dict[str, Any]) -> list[list[str]]:
    fiber = _published_fiber(synthesis)
    joined: dict[str, set[str]] = {node["id"]: set() for node in synthesis["backbone"]}
    joined |= {city: set(neighbors) for city, neighbors in fiber.items()}
    unplaced = {node["id"] for node in synthesis["backbone"]}
    groups: list[list[str]] = []
    while unplaced:
        reached = _reached(joined, min(unplaced))
        groups.append(sorted(unplaced & reached))
        unplaced -= reached
    return groups


def ordered_fiber_miles(synthesis: dict[str, Any]) -> float:
    segments: list[float] = [
        link["distance_miles"] for link in synthesis["paths"] if link["link_kind"] == FIBER
    ]
    return sum(segments)


_ARRIVING = "into "
_LEAVING = "out of "
_SINK = "a peer"


def _joined_by(pairs: set[frozenset[str]]) -> dict[str, set[str]]:
    ends = [sorted(pair) for pair in pairs if len(pair) == 2]
    return _joined_to([(both[0], both[1]) for both in ends])


def _capacity(
    joined: dict[str, set[str]], city: str, peers: frozenset[str], per_peer: int
) -> dict[str, dict[str, int]]:
    plenty = len(peers) * per_peer + 1
    left: dict[str, dict[str, int]] = {
        _ARRIVING + place: {_LEAVING + place: plenty if place in peers else 1}
        for place in joined
        if place != city
    }
    for place, neighbours in joined.items():
        left[_LEAVING + place] = {_ARRIVING + neighbour: 1 for neighbour in neighbours}
    for peer in peers:
        if peer in joined:
            left[_LEAVING + peer][_SINK] = per_peer
    left[_SINK] = {}
    for tail, heads in list(left.items()):
        for head in heads:
            left.setdefault(head, {}).setdefault(tail, 0)
    return left


def _walk_to_a_peer(
    left: dict[str, dict[str, int]], source: str
) -> dict[str, str] | None:
    came: dict[str, str] = {source: source}
    queue: deque[str] = deque([source])
    while queue:
        tail = queue.popleft()
        for head, spare in left[tail].items():
            if spare > 0 and head not in came:
                came[head] = tail
                if head == _SINK:
                    return came
                queue.append(head)
    return None


def _sellable_over(
    joined: dict[str, set[str]], city: str, peers: frozenset[str], per_peer: int
) -> int:
    left = _capacity(joined, city, peers, per_peer)
    source = _LEAVING + city
    if source not in left:
        return 0
    sold = 0
    came = _walk_to_a_peer(left, source)
    while came is not None:
        head = _SINK
        while head != source:
            tail = came[head]
            left[tail][head] -= 1
            left[head][tail] += 1
            head = tail
        sold += 1
        came = _walk_to_a_peer(left, source)
    return sold


def sellable_ways_out(
    fiber_by_carrier: dict[str, set[frozenset[str]]],
    city: str,
    peers: frozenset[str],
    per_peer: int,
) -> int:
    return min(
        sum(
            _sellable_over(_joined_by(pairs), city, peers, per_peer)
            for pairs in fiber_by_carrier.values()
        ),
        len(peers) * per_peer,
    )
