"""Score a carrier PoP's strength: link reach, compass spread, and straightness.

Cores are chosen for strength rather than mileage (the source mapbook has no
distances), so this scoring is the search's primary objective. It is isolated
here because it depends only on the precomputed graph context, not on the search
machinery that consumes it.
"""

from __future__ import annotations

import math

from wan_designer.model import DesignInputs, Vertex, haversine_miles
from wan_designer.graphs import reconstruct_path


def link_bearing(origin: Vertex, neighbor: Vertex) -> float:
    """Initial compass bearing in degrees from one vertex toward another."""
    lat1, lat2 = math.radians(origin.lat), math.radians(neighbor.lat)
    delta_lon = math.radians(neighbor.lon - origin.lon)
    x = math.sin(delta_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(
        delta_lon
    )
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0

def link_octants(
    pop_id: str,
    adjacency: dict[str, list[tuple[str, float]]],
    pop_by_id: dict[str, Vertex],
) -> set[int]:
    """The distinct compass octants (of eight) the PoP's links point toward."""
    origin = pop_by_id[pop_id]
    return {
        int(((link_bearing(origin, pop_by_id[neighbor]) + 22.5) % 360.0) // 45.0)
        for neighbor, _weight in adjacency[pop_id]
    }

def vertex_straightness(
    pop_id: str,
    pop_by_id: dict[str, Vertex],
    predecessors: dict[str, str],
) -> float:
    """Mean directness to reachable PoPs: straight-line over routed geometry."""
    origin = pop_by_id[pop_id]
    ratios: list[float] = []
    for dest_id in predecessors:
        path = reconstruct_path(pop_id, dest_id, predecessors)
        routed = sum(
            haversine_miles(pop_by_id[path[index]], pop_by_id[path[index + 1]])
            for index in range(len(path) - 1)
        )
        straight = haversine_miles(origin, pop_by_id[dest_id])
        if routed > 0.0:
            ratios.append(straight / routed)
    return sum(ratios) / len(ratios) if ratios else 0.0

def core_strength(
    pop_id: str,
    inputs: DesignInputs,
    pop_by_id: dict[str, Vertex],
    max_degree: int,
    compass_octants: int,
) -> float:
    """Score a PoP's strength: reach plus spread plus straightness (~0..3)."""
    degree = len(inputs.adjacency[pop_id])
    spread = len(link_octants(pop_id, inputs.adjacency, pop_by_id))
    straight = vertex_straightness(pop_id, pop_by_id, inputs.all_predecessors[pop_id])
    return degree / max_degree + spread / compass_octants + straight
