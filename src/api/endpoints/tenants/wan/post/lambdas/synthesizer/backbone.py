from __future__ import annotations

import math
from dataclasses import dataclass, replace
from itertools import combinations

from synthesizer.ceiling import PathProofInputs, independent_paths
from synthesizer.input_graph import FiberSegment, carriers_along, link_key
from synthesizer.graphs import (
    adjacency_by_carrier,
    articulation_points,
    build_adjacency,
    connected_components,
    dijkstra,
    path_link_keys,
    reachable_over,
    reconstruct_path,
    undirected_adjacency,
)
from synthesizer.model import LINK_FOR_PIN, LINK_FOR_TARGET, SynthesisPath
from synthesizer.survivable import FiberInputs, choose_fiber
from synthesizer.validation import diverse_path_count


def path_geometry_miles(
    path: tuple[str, ...],
    fiber_segments: dict[tuple[str, str], FiberSegment],
) -> float:
    return sum(
        fiber_segments[link_key(path[index], path[index + 1])].distance_miles
        for index in range(len(path) - 1)
    )


@dataclass(frozen=True)
class BackboneConstraints:
    removed_pairs: frozenset[tuple[str, str]] = frozenset()
    number_of_diverse_paths: int = 3
    forced_pairs: frozenset[tuple[str, str]] = frozenset()
    seat_cap: int | None = None


@dataclass(frozen=True)
class BackboneMesh:
    paths: list[SynthesisPath]
    lower_bound_miles: float


@dataclass(frozen=True)
class _DrawnFiber:
    backbone_ids: tuple[str, ...]
    distances: dict[str, dict[str, float]]
    selected: dict[tuple[str, str], FiberSegment]
    selected_by_carrier: dict[str, dict[str, list[tuple[str, float]]]]
    whole: dict[tuple[str, str], FiberSegment]
    constraints: BackboneConstraints


def _fiber_of(paths: list[SynthesisPath]) -> tuple[set[str], set[tuple[str, str]]]:
    segments: set[tuple[str, str]] = set()
    for use in paths:
        segments |= path_link_keys(use.path)
    return {city for segment in segments for city in segment}, segments


def _one_network(paths: list[SynthesisPath], backbone_ids: tuple[str, ...]) -> bool:
    cities, segments = _fiber_of(paths)
    return len(connected_components(cities | set(backbone_ids), segments)) == 1


def _cut_cities(
    paths: list[SynthesisPath], backbone_ids: tuple[str, ...]
) -> set[str]:
    cities, segments = _fiber_of(paths)
    return articulation_points(cities | set(backbone_ids), segments)


def _no_single_point_of_failure(
    paths: list[SynthesisPath], backbone_ids: tuple[str, ...]
) -> bool:
    return not _cut_cities(paths, backbone_ids)


def _pinned_path(
    pair: tuple[str, str],
    by_carrier: dict[str, dict[str, list[tuple[str, float]]]],
    fiber_segments: dict[tuple[str, str], FiberSegment],
) -> SynthesisPath | None:
    near, far = pair
    maps = by_carrier or {"": build_adjacency(fiber_segments)}
    drawn: list[tuple[str, ...]] = []
    for _carrier, adjacency in sorted(maps.items()):
        _distances, predecessors = dijkstra(adjacency, near)
        path = reconstruct_path(near, far, predecessors)
        if path:
            drawn.append(path)
    if not drawn:
        return None
    path = min(drawn, key=lambda one: (path_geometry_miles(one, fiber_segments), one))
    return SynthesisPath(
        "backbone_mesh", near, far, path,
        path_geometry_miles(path, fiber_segments), LINK_FOR_PIN,
        carrier=_carrier_of(path, fiber_segments),
    )


def _carrier_of(
    path: tuple[str, ...], fiber_segments: dict[tuple[str, str], FiberSegment]
) -> str:
    owners = carriers_along(path, fiber_segments)
    return min(owners) if owners else ""


def _proved_over(
    site: str,
    fiber: dict[tuple[str, str], FiberSegment],
    by_carrier: dict[str, dict[str, list[tuple[str, float]]]],
    drawn: _DrawnFiber,
) -> list[tuple[str, ...]]:
    constraints = drawn.constraints
    peers = tuple(
        node
        for node in drawn.backbone_ids
        if node == site or link_key(site, node) not in constraints.removed_pairs
    )
    proof = PathProofInputs(
        peers, build_adjacency(fiber),
        constraints.number_of_diverse_paths, constraints.seat_cap, by_carrier,
    )
    return sorted(
        independent_paths(site, proof),
        key=lambda path: (path_geometry_miles(path, fiber), path),
    )[: constraints.number_of_diverse_paths]


def _ways_out_of(site: str, drawn: _DrawnFiber) -> list[tuple[str, ...]]:
    return _proved_over(site, drawn.selected, drawn.selected_by_carrier, drawn)


def _laid(drawn: _DrawnFiber, pinned: list[SynthesisPath]) -> list[SynthesisPath]:
    laid: dict[tuple[str, ...], SynthesisPath] = {
        min(use.path, use.path[::-1]): use for use in pinned
    }
    for site in sorted(drawn.backbone_ids):
        for path in _ways_out_of(site, drawn):
            key = min(path, path[::-1])
            held = laid.get(key)
            if held is None:
                laid[key] = SynthesisPath(
                    "backbone_mesh", path[0], path[-1], path,
                    path_geometry_miles(path, drawn.whole), LINK_FOR_TARGET, (site,),
                    _carrier_of(path, drawn.whole),
                )
            elif held.reason == LINK_FOR_TARGET and site not in held.requested_by:
                laid[key] = replace(
                    held, requested_by=tuple(sorted((*held.requested_by, site)))
                )
    return [laid[key] for key in sorted(laid)]


def _pairs_across(
    city: str, paths: list[SynthesisPath], drawn: _DrawnFiber
) -> list[tuple[str, str]]:
    cities, segments = _fiber_of(paths)
    places = cities | set(drawn.backbone_ids)
    apart = {
        place: index
        for index, piece in enumerate(connected_components(places - {city}, segments))
        for place in piece
    }
    sides: dict[int, list[str]] = {}
    for site in sorted(set(drawn.backbone_ids) - {city}):
        sides.setdefault(apart[site], []).append(site)
    split = sorted({apart[near] for near in undirected_adjacency(places, segments)[city]})
    pairs = [
        (near, far)
        for left, right in combinations(split, 2)
        for near in sides.get(left, [])
        for far in sides.get(right, [])
    ]
    return sorted(
        pairs,
        key=lambda ends: (drawn.distances.get(ends[0], {}).get(ends[1], math.inf), ends),
    )


def _on_land(
    fiber: dict[tuple[str, str], FiberSegment]
) -> dict[tuple[str, str], FiberSegment]:
    return {segment: link for segment, link in fiber.items() if not link.submarine}


def _path_around(
    city: str, paths: list[SynthesisPath], drawn: _DrawnFiber
) -> SynthesisPath | None:
    fiber = {
        segment: link for segment, link in drawn.whole.items() if city not in segment
    }
    by_carrier = adjacency_by_carrier(fiber)
    land = _on_land(fiber)
    land_by_carrier = adjacency_by_carrier(land)
    reach = reachable_over(build_adjacency(_on_land(drawn.whole)))
    for near, far in _pairs_across(city, paths, drawn):
        joined = far in reach.get(near, frozenset())
        found = _pinned_path(
            (near, far),
            land_by_carrier if joined else by_carrier,
            land if joined else fiber,
        )
        if found is None:
            continue
        return replace(found, reason=LINK_FOR_TARGET)
    return None


def _relieved(paths: list[SynthesisPath], drawn: _DrawnFiber) -> list[SynthesisPath]:
    relieved = list(paths)
    if drawn.constraints.number_of_diverse_paths < 2:
        return relieved
    beyond_help: set[str] = set()
    while True:
        cut = sorted(_cut_cities(relieved, drawn.backbone_ids) - beyond_help)
        if not cut:
            return relieved
        added = _path_around(cut[0], relieved, drawn)
        if added is None:
            beyond_help.add(cut[0])
            continue
        relieved.append(added)


def _needed(
    paths: list[SynthesisPath], backbone_ids: tuple[str, ...], target: int
) -> list[SynthesisPath]:
    kept = list(paths)
    held = {site: min(target, diverse_path_count(kept, site)) for site in backbone_ids}
    intact = _no_single_point_of_failure(kept, backbone_ids)
    for spare in sorted(paths, key=lambda use: (-use.distance_miles, use.path)):
        if spare.reason == LINK_FOR_PIN:
            continue
        left = [use for use in kept if use is not spare]
        if any(
            min(target, diverse_path_count(left, site)) < held[site] for site in backbone_ids
        ):
            continue
        if not _one_network(left, backbone_ids):
            continue
        if intact and not _no_single_point_of_failure(left, backbone_ids):
            continue
        kept = left
    return kept


def _selected_fiber(
    backbone_ids: tuple[str, ...],
    fiber_segments: dict[tuple[str, str], FiberSegment],
    constraints: BackboneConstraints,
    by_carrier: dict[str, dict[str, list[tuple[str, float]]]],
) -> tuple[frozenset[tuple[str, str]], float, list[SynthesisPath]]:
    choice = choose_fiber(FiberInputs(
        backbone_ids, fiber_segments,
        constraints.number_of_diverse_paths, constraints.seat_cap,
        by_carrier,
    ))
    drawn = (
        _pinned_path(pair, by_carrier, fiber_segments)
        for pair in sorted(constraints.forced_pairs)
    )
    pinned = [use for use in drawn if use is not None]
    segments = set(choice.segments)
    for use in pinned:
        segments |= path_link_keys(use.path)
    return frozenset(segments), choice.lower_bound_miles, pinned


def backbone_mesh(
    backbone_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    fiber_segments: dict[tuple[str, str], FiberSegment],
    constraints: BackboneConstraints = BackboneConstraints(),
) -> BackboneMesh:
    whole_by_carrier = adjacency_by_carrier(fiber_segments)
    segments, floor, pinned = _selected_fiber(
        backbone_ids, fiber_segments, constraints, whole_by_carrier
    )
    selected = {segment: fiber_segments[segment] for segment in sorted(segments)}
    drawn = _DrawnFiber(
        backbone_ids, all_distances, selected, adjacency_by_carrier(selected),
        fiber_segments, constraints,
    )
    laid = _relieved(_laid(drawn, pinned), drawn)
    return BackboneMesh(
        _needed(laid, backbone_ids, constraints.number_of_diverse_paths), floor
    )
