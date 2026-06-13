"""Optimize a three-tier core/aggregation/access WAN over the carrier graph.

Core nodes are chosen for *strength*, not distance. The mapbook lists no
mileage, so straight-line distance between PoPs is never used as a cost.
A PoP's strength combines reach (degree), spread (how many compass
directions its links cover), and straightness (how directly it reaches
the rest of the graph). The strongest PoPs become cores; more cores are
added only when fewer cannot satisfy the hard constraints.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from wan_designer.model import (
    AccessEdge,
    Design,
    DesignInputs,
    DesignMetrics,
    DesignParams,
    Node,
    PathUse,
    PhysicalEdge,
    edge_key,
    haversine_miles,
)
from wan_designer.graphs import (
    dijkstra,
    node_disjoint_paths_to_cores,
    path_edge_keys,
    reconstruct_path,
)

COMPASS_OCTANTS = 8

def unit_adjacency(
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> dict[str, list[tuple[str, float]]]:
    """Build a unit-weight adjacency map: every fiber span counts the same.

    The mapbook has no distances, so routing weights every span equally
    rather than by a fabricated straight-line mileage.
    """
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for left, right in physical_edges:
        adjacency.setdefault(left, []).append((right, 1.0))
        adjacency.setdefault(right, []).append((left, 1.0))
    for neighbors in adjacency.values():
        neighbors.sort()
    return adjacency

def link_bearing(origin: Node, neighbor: Node) -> float:
    """Initial compass bearing in degrees from one node toward another."""
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
    pop_by_id: dict[str, Node],
) -> set[int]:
    """The distinct compass octants (of eight) the PoP's links point toward."""
    origin = pop_by_id[pop_id]
    return {
        int(((link_bearing(origin, pop_by_id[neighbor]) + 22.5) % 360.0) // 45.0)
        for neighbor, _weight in adjacency[pop_id]
    }

def node_straightness(
    pop_id: str,
    pop_by_id: dict[str, Node],
    predecessors: dict[str, str],
) -> float:
    """Mean directness to reachable PoPs: straight-line over routed geometry.

    Near 1.0 means the PoP's paths head straight at their destinations;
    lower values mean detours and odd, near-right-angle turns.
    """
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
    pop_by_id: dict[str, Node],
    max_degree: int,
) -> float:
    """Score a PoP as a core: reach plus spread plus straightness.

    Each term is normalized to roughly 0..1, so a strong hub that
    radiates in every direction and reaches the graph directly scores
    near 3.0, and a low-degree corridor PoP scores near 1.0.
    """
    degree = len(inputs.adjacency[pop_id])
    spread = len(link_octants(pop_id, inputs.adjacency, pop_by_id))
    straight = node_straightness(pop_id, pop_by_id, inputs.all_predecessors[pop_id])
    return degree / max_degree + spread / COMPASS_OCTANTS + straight

def rank_core_candidates(
    eligible_ids: set[str],
    inputs: DesignInputs,
    pop_by_id: dict[str, Node],
    limit: int,
) -> list[str]:
    """Rank eligible PoPs strongest-first and keep the top `limit`."""
    max_degree = max((len(inputs.adjacency[pop_id]) for pop_id in eligible_ids), default=1)
    ranked = sorted(
        eligible_ids,
        key=lambda pop_id: (-core_strength(pop_id, inputs, pop_by_id, max_degree), pop_id),
    )
    return ranked[:limit]

def path_geometry_miles(
    path: tuple[str, ...],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> float:
    """Sum the per-span straight-line estimate along a routed path.

    This is a display estimate only; it never influences node selection.
    """
    return sum(
        physical_edges[edge_key(path[index], path[index + 1])].distance_miles
        for index in range(len(path) - 1)
    )

def aggregation_core_paths(
    aggregation_id: str,
    core_ids: tuple[str, ...],
    adjacency: dict[str, list[tuple[str, float]]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> tuple[float, list[PathUse]]:
    """Route an aggregation to two distinct cores over node-disjoint paths.

    Returns the total hop distance and one ``aggregation_to_core`` PathUse
    per core, or ``(math.inf, [])`` if two node-disjoint paths to two
    distinct cores do not exist over the physical graph.
    """
    total, paths = node_disjoint_paths_to_cores(adjacency, aggregation_id, core_ids, 2)
    if not paths:
        return math.inf, []
    uses = [
        PathUse(
            "aggregation_to_core",
            aggregation_id,
            path[-1],
            path,
            path_geometry_miles(path, physical_edges),
        )
        for path in paths
    ]
    return total, uses

def core_mesh_paths(
    core_ids: tuple[str, ...],
    all_distances: dict[str, dict[str, float]],
    all_predecessors: dict[str, dict[str, str]],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> list[PathUse]:
    """Route a shortest path between every pair of cores (the full mesh)."""
    uses: list[PathUse] = []
    for left, right in itertools.combinations(core_ids, 2):
        distance = all_distances[left].get(right, math.inf)
        if not math.isfinite(distance):
            return []
        path = reconstruct_path(left, right, all_predecessors[left])
        uses.append(
            PathUse("core_mesh", left, right, path, path_geometry_miles(path, physical_edges))
        )
    return uses

@dataclass
class _DesignDraft:
    access_edges: list[AccessEdge]
    selected_aggregation_ids: set[str]
    path_uses: list[PathUse]

def aggregation_core_map(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
) -> dict[str, tuple[float, list[PathUse]]]:
    """Map each eligible aggregation to its node-disjoint routing to two cores."""
    allowed = sorted(inputs.eligible_aggregation_ids - set(core_ids))
    feasible: dict[str, tuple[float, list[PathUse]]] = {}
    for aggregation_id in allowed:
        cost, paths = aggregation_core_paths(
            aggregation_id, core_ids, inputs.adjacency, inputs.physical_edges
        )
        if math.isfinite(cost):
            feasible[aggregation_id] = (cost, paths)
    return feasible

def best_aggregation_pair(
    access: Node,
    aggregation_core: dict[str, tuple[float, list[PathUse]]],
    by_id: dict[str, Node],
    params: DesignParams,
) -> tuple[tuple[float, str], tuple[float, str]] | None:
    """Pick the two nearest aggregations to dual-home one access node.

    The access tail is a new build, so straight-line distance from the
    demand site to the aggregation PoP is a legitimate cost here.
    """
    ranked = sorted(
        (
            (haversine_miles(access, by_id[aggregation_id]), aggregation_id)
            for aggregation_id in aggregation_core
        ),
        key=lambda item: (item[0], item[1]),
    )[: params.aggregation_candidates_per_access]
    best_cost = math.inf
    chosen: tuple[tuple[float, str], tuple[float, str]] | None = None
    for left, right in itertools.combinations(ranked, 2):
        pair_cost = left[0] + right[0]
        if pair_cost < best_cost:
            best_cost = pair_cost
            chosen = (left, right)
    return chosen

def finalize_design(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    params: DesignParams,
    draft: _DesignDraft,
) -> Design:
    """Compute edge sets, mileage estimate, and score for a design draft."""
    physical_edge_keys: set[tuple[str, str]] = set()
    for path_use in draft.path_uses:
        physical_edge_keys.update(path_edge_keys(path_use.path))

    access_miles = sum(edge.distance_miles for edge in draft.access_edges)
    physical_miles = sum(
        inputs.physical_edges[key].distance_miles for key in physical_edge_keys
    )
    score = (
        access_miles
        + physical_miles
        + params.aggregation_penalty_miles * len(draft.selected_aggregation_ids)
    )
    carrier_on_paths = {node_id for use in draft.path_uses for node_id in use.path}
    transit_ids = tuple(
        sorted(carrier_on_paths - set(core_ids) - draft.selected_aggregation_ids)
    )
    return Design(
        core_ids=core_ids,
        aggregation_ids=tuple(sorted(draft.selected_aggregation_ids)),
        transit_ids=transit_ids,
        access_edges=draft.access_edges,
        physical_edge_keys=physical_edge_keys,
        path_uses=draft.path_uses,
        metrics=DesignMetrics(score, access_miles, physical_miles),
    )

def build_design_for_cores(
    core_ids: tuple[str, ...],
    inputs: DesignInputs,
    params: DesignParams,
) -> Design | None:
    """Assemble a full three-tier design for one fixed set of core PoPs."""
    aggregation_core = aggregation_core_map(core_ids, inputs)
    if len(aggregation_core) < 2:
        return None

    by_id = {node.id: node for node in inputs.carrier_pops}
    access_edges: list[AccessEdge] = []
    selected: set[str] = set()
    for access in inputs.access_nodes:
        chosen = best_aggregation_pair(access, aggregation_core, by_id, params)
        if chosen is None:
            return None
        for distance, aggregation_id in chosen:
            access_edges.append(AccessEdge(access.id, aggregation_id, distance))
            selected.add(aggregation_id)

    path_uses = core_mesh_paths(
        core_ids, inputs.all_distances, inputs.all_predecessors, inputs.physical_edges
    )
    if not path_uses:
        return None  # the cores do not form a full mesh over the carrier graph
    for aggregation_id in sorted(selected):
        path_uses.extend(aggregation_core[aggregation_id][1])

    draft = _DesignDraft(access_edges, selected, path_uses)
    return finalize_design(core_ids, inputs, params, draft)

def compute_eligible_ids(
    carrier_pops: list[Node],
    roles: dict[str, str],
    adjacency: dict[str, list[tuple[str, float]]],
    allow_roadm_aggregation: bool,
) -> set[str]:
    """Carrier PoPs that may serve as core or aggregation nodes.

    A PoP needs at least two physical links to ever be dual-homed to two
    cores, so degree-one PoPs (spurs) are excluded regardless of role.
    ROADM PoPs are excluded unless explicitly allowed.
    """
    return {
        pop.id
        for pop in carrier_pops
        if (allow_roadm_aggregation or roles.get(pop.id, "aggregator") == "aggregator")
        and len(adjacency.get(pop.id, [])) >= 2
    }

def all_pairs_shortest(
    carrier_pops: list[Node],
    adjacency: dict[str, list[tuple[str, float]]],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, str]]]:
    """Run Dijkstra from every Carrier PoP for reuse across core sets."""
    all_distances: dict[str, dict[str, float]] = {}
    all_predecessors: dict[str, dict[str, str]] = {}
    for pop in carrier_pops:
        all_distances[pop.id], all_predecessors[pop.id] = dijkstra(adjacency, pop.id)
    return all_distances, all_predecessors

def validate_pop_graph(
    carrier_pops: list[Node],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    adjacency: dict[str, list[tuple[str, float]]],
) -> None:
    """Raise if the physical edge graph and Carrier PoP set are inconsistent."""
    pop_ids = {pop.id for pop in carrier_pops}
    physical_node_ids = {node_id for edge in physical_edges for node_id in edge}
    if not pop_ids.issuperset(physical_node_ids):
        raise ValueError("Physical edge graph references unknown Carrier PoP IDs")
    missing_pops = sorted(pop_ids - set(adjacency))
    if missing_pops:
        names = ", ".join(node.name for node in carrier_pops if node.id in missing_pops)
        raise ValueError(f"Carrier PoPs missing from physical edge graph: {names}")

def grow_feasible_cores(
    inputs: DesignInputs,
    params: DesignParams,
    ranked: list[str],
) -> Design:
    """Take the strongest cores, adding more until the constraints hold.

    Starts at ``params.core_count`` (the minimum) and grows the core set
    one strong PoP at a time. ``build_design_for_cores`` only returns a
    design when the hard constraints hold, so the first non-None result
    is the strongest feasible core set.
    """
    for size in range(params.core_count, len(ranked) + 1):
        design = build_design_for_cores(tuple(ranked[:size]), inputs, params)
        if design is not None:
            return design
    raise ValueError(f"No feasible design with {params.core_count} or more cores")

def optimize_three_tier_design(
    nodes: list[Node],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    roles: dict[str, str],
    params: DesignParams,
) -> Design:
    """Optimize a three-tier WAN over the Carrier graph for the given parameters."""
    if params.core_count < 2:
        raise ValueError("core_count (the minimum number of cores) must be at least 2")

    access_nodes = [node for node in nodes if node.kind != "carrier_pop"]
    carrier_pops = [node for node in nodes if node.kind == "carrier_pop"]
    adjacency = unit_adjacency(physical_edges)
    validate_pop_graph(carrier_pops, physical_edges, adjacency)
    all_distances, all_predecessors = all_pairs_shortest(carrier_pops, adjacency)

    eligible_ids = compute_eligible_ids(
        carrier_pops, roles, adjacency, params.allow_roadm_aggregation
    )
    if len(eligible_ids) < max(2, params.core_count):
        raise ValueError("Not enough eligible Carrier aggregation/core PoPs")

    inputs = DesignInputs(
        access_nodes=access_nodes,
        carrier_pops=carrier_pops,
        physical_edges=physical_edges,
        eligible_aggregation_ids=eligible_ids,
        adjacency=adjacency,
        all_distances=all_distances,
        all_predecessors=all_predecessors,
    )
    pop_by_id = {pop.id: pop for pop in carrier_pops}
    ranked = rank_core_candidates(
        eligible_ids, inputs, pop_by_id, params.core_candidate_limit
    )
    if len(ranked) < params.core_count:
        raise ValueError("Not enough reachable core candidates")

    return grow_feasible_cores(inputs, params, ranked)
