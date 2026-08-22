from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from synthesizer.ceiling import PathProofInputs, independent_path_ceiling
from synthesizer.input_graph import Site, haversine_miles
from synthesizer.model import SynthesisInputs
from synthesizer.graphs import reconstruct_path


def link_bearing(origin: Site, neighbor: Site) -> float:
    lat1, lat2 = math.radians(origin.lat), math.radians(neighbor.lat)
    delta_lon = math.radians(neighbor.lon - origin.lon)
    x = math.sin(delta_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(
        delta_lon
    )
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0

def link_sectors(
    pop_id: str,
    adjacency: dict[str, list[tuple[str, float]]],
    pop_by_id: dict[str, Site],
    compass_sector_count: int,
) -> set[int]:
    width = 360.0 / compass_sector_count
    origin = pop_by_id[pop_id]
    return {
        int(((link_bearing(origin, pop_by_id[neighbor]) + width / 2.0) % 360.0) // width)
        for neighbor, _weight in adjacency[pop_id]
    }

def site_straightness(
    pop_id: str,
    pop_by_id: dict[str, Site],
    predecessors: dict[str, str],
) -> float:
    origin = pop_by_id[pop_id]
    ratios: list[float] = []
    for dest_id in predecessors:
        path = reconstruct_path(pop_id, dest_id, predecessors)
        along_path = sum(
            haversine_miles(pop_by_id[path[index]], pop_by_id[path[index + 1]])
            for index in range(len(path) - 1)
        )
        straight = haversine_miles(origin, pop_by_id[dest_id])
        if along_path > 0.0:
            ratios.append(straight / along_path)
    return sum(ratios) / len(ratios) if ratios else 0.0

@dataclass(frozen=True)
class DiversePathBounds:
    per_site: Mapping[str, int]
    largest: int


def diverse_path_bounds(
    candidate_ids: set[str],
    adjacency: dict[str, list[tuple[str, float]]],
) -> DiversePathBounds:
    sites = tuple(sorted(candidate_ids))
    ground = PathProofInputs(sites, adjacency)
    per_site = {site: independent_path_ceiling(site, ground) for site in sites}
    return DiversePathBounds(per_site, max((*per_site.values(), 1)))


def backbone_strength(
    pop_id: str,
    inputs: SynthesisInputs,
    pop_by_id: dict[str, Site],
    bounds: DiversePathBounds,
    compass_sector_count: int,
) -> float:
    diverse = bounds.per_site.get(pop_id, 0)
    spread = len(link_sectors(pop_id, inputs.adjacency, pop_by_id, compass_sector_count))
    straight = site_straightness(pop_id, pop_by_id, inputs.all_predecessors[pop_id])
    return diverse / bounds.largest + spread / compass_sector_count + straight
