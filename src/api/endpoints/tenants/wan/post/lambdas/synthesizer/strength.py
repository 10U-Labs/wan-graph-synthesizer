"""Score a carrier PoP's strength: path diversity, compass spread, and straightness.

Backbone nodes are chosen for strength rather than mileage (the source mapbook has
no distances), so this scoring is the search's primary objective. It is isolated
here because it depends only on the precomputed graph context, not on the search
machinery that consumes it.

The protection term counts diverse paths rather than fiber segments. A city can have a
great many segments and funnel almost all of them through one or two upstream cities, in
which case the segments are one path wearing many coats; another can have few segments and
send every one of them somewhere separate. Measured over the merged carrier files, Los
Angeles has eighteen segments and carries six diverse paths while Cheyenne has eleven and
carries eight, so ranking the two by segments ranks them backwards.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from synthesizer.ceiling import PathProofInputs, independent_path_ceiling
from synthesizer.input_graph import Vertex, haversine_miles
from synthesizer.model import DesignInputs
from synthesizer.graphs import reconstruct_path


def link_bearing(origin: Vertex, neighbor: Vertex) -> float:
    """Initial compass bearing in degrees from one vertex toward another."""
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
    pop_by_id: dict[str, Vertex],
    compass_sector_count: int,
) -> set[int]:
    """The distinct compass sectors the PoP's links point toward.

    The compass is divided into ``compass_sector_count`` equal sectors, each centred on a
    direction rather than starting at one, so a due-north link lands in the middle of
    sector zero rather than on its edge. Deriving the width here from the same number
    the score divides by is what keeps the direction term between 0 and 1: at eight,
    the sectors are the 45-degree octants with the 22.5-degree offset this always used.
    """
    width = 360.0 / compass_sector_count
    origin = pop_by_id[pop_id]
    return {
        int(((link_bearing(origin, pop_by_id[neighbor]) + width / 2.0) % 360.0) // width)
        for neighbor, _weight in adjacency[pop_id]
    }

def vertex_straightness(
    pop_id: str,
    pop_by_id: dict[str, Vertex],
    predecessors: dict[str, str],
) -> float:
    """Mean directness to reachable PoPs: straight-line over the path's own geometry."""
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
    """Every candidate site's diverse path bound, and the largest bound among them.

    ``per_site`` is the bound itself and ``largest`` is what the strength score divides
    by, so the protection term stays within 0..1 and keeps the weighting the three terms
    were given. A site the substrate says nothing about has no entry and scores zero,
    which is the truth about it: no fiber in the inputs is no path anyone can path.
    """

    per_site: Mapping[str, int]
    largest: int


def diverse_path_bounds(
    candidate_ids: set[str],
    adjacency: dict[str, list[tuple[str, float]]],
) -> DiversePathBounds:
    """Each candidate site's diverse path bound, computed once for the whole run.

    The bound counts paths from a site to *every other candidate site* that share no
    city along the way -- one max flow per site (see
    :func:`synthesizer.ceiling.independent_path_ceiling`). Counting to the candidates
    rather than to a chosen backbone is what makes it affordable: diversity is otherwise
    a property of the set, changing with every set the search considers, and a max flow
    inside a loop that enumerates millions of them is not something anyone can pay for.

    The bound is also honest about which way it errs. Any backbone the search settles on
    is a subset of these candidates, so it offers a path fewer places to end and no
    choice of set can exceed the bound. Adding fiber can only raise a maximum flow, so
    the bound stays true as the map grows -- the same reason the seed contract measures
    against the pins rather than against a design nobody has built yet.

    The exact set-dependent measure is not replaced, only kept out of the hot loop: the
    coverage growth step still asks what a candidate's fiber can carry against the actual
    grown backbone (see :func:`synthesizer.coverage.candidate_mesh_ceiling`), because it
    weighs a handful of candidates rather than millions of sets.

    The tenant's backup path multiple is deliberately not applied here, and the reason is
    the same one that makes this bound affordable. It counts paths to every other candidate,
    so every city on the map is a peer a path may legitimately end at -- and a path that
    ends where it was going is not a detour, whatever its length. A crossing to a landing
    point is measured against the direct distance to that same landing point and comes out
    at one. So the bound has almost nothing to say at this scale: over the carrier files in
    ``data/`` it moves no candidate's score at all, while costing more than ten times what
    the count itself does. It bites where the peers are an actual backbone and the far side
    of an ocean is not among them, which is the growth step above and the mesh routing,
    and it is applied at both.
    """
    sites = tuple(sorted(candidate_ids))
    ground = PathProofInputs(sites, adjacency)
    per_site = {site: independent_path_ceiling(site, ground) for site in sites}
    return DiversePathBounds(per_site, max((*per_site.values(), 1)))


def backbone_strength(
    pop_id: str,
    inputs: DesignInputs,
    pop_by_id: dict[str, Vertex],
    bounds: DiversePathBounds,
    compass_sector_count: int,
) -> float:
    """Score a PoP's strength: diversity plus spread plus straightness (~0..3).

    ``compass_sector_count`` both cuts the compass into sectors and divides the count of
    sectors the links reach, so the direction term stays within 0..1 whatever the
    setting holds and the three terms keep the weighting they were given.

    The first term is how many diverse paths the site's fiber can carry rather than how
    many segments touch it (see :func:`diverse_path_bounds`). Spread and straightness stay
    as they were: spread and diversity are related but not the same, and straightness is
    about haul rather than protection.
    """
    diverse = bounds.per_site.get(pop_id, 0)
    spread = len(link_sectors(pop_id, inputs.adjacency, pop_by_id, compass_sector_count))
    straight = vertex_straightness(pop_id, pop_by_id, inputs.all_predecessors[pop_id])
    return diverse / bounds.largest + spread / compass_sector_count + straight
