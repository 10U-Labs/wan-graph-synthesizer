"""Validate a design against the hard resilience requirements."""

from __future__ import annotations

import itertools

from wan_designer.model import (
    Design,
    DesignMetrics,
    Vertex,
    PhysicalEdge,
    ValidationReport,
    edge_key,
    is_carrier_pop,
)
from wan_designer.graphs import (
    articulation_points,
    connected_components,
    dijkstra,
    is_two_edge_connected,
    vertex_disjoint_paths_to_cores,
)


# Every core must link to at least this many other cores -- but only once the core
# tier is larger than the floor itself, since fewer cores cannot reach it.
CORE_BACKBONE_MIN_DEGREE = 3


def backbone_degree_deficient(
    core_ids: tuple[str, ...],
    backbone_degrees: dict[str, int],
    vertices_by_id: dict[str, Vertex],
) -> list[dict[str, object]]:
    """Cores with too few backbone links, once there are more cores than the floor.

    With ``CORE_BACKBONE_MIN_DEGREE`` or fewer cores the rule cannot be met (a core
    has only that many peers), so the list is empty.
    """
    if len(core_ids) <= CORE_BACKBONE_MIN_DEGREE:
        return []
    return [
        {"id": core_id, "name": vertices_by_id[core_id].name, "degree": degree}
        for core_id, degree in sorted(backbone_degrees.items())
        if degree < CORE_BACKBONE_MIN_DEGREE
    ]


def design_edge_set(design: Design) -> set[tuple[str, str]]:
    """All edges in the design: selected physical edges plus access edges."""
    edges = set(design.physical_edge_keys)
    edges.update(edge_key(edge.source, edge.target) for edge in design.access_edges)
    return edges

def included_vertex_ids(design: Design) -> set[str]:
    """Every vertex id that participates in the design."""
    ids = set(design.core_ids) | set(design.aggregation_ids) | set(design.transit_ids)
    ids.update(vertex_id for edge in design.physical_edge_keys for vertex_id in edge)
    ids.update(edge.source for edge in design.access_edges)
    ids.update(edge.target for edge in design.access_edges)
    return ids

def design_badness(vertices: list[Vertex], design: Design) -> tuple[int, int, int]:
    """Disconnection, articulation, and degree-deficit counts as a sort key."""
    validation = validate_design(vertices, design)
    return (
        0 if validation["connected"] else validation["component_count"],
        len(validation["articulation_points"]),
        len(validation["degree_deficient_vertices"]),
    )

def with_updated_physical_edges(
    design: Design,
    physical_edge_keys: set[tuple[str, str]],
) -> Design:
    """Copy a design with a new physical edge set and refreshed transit tier."""
    carrier_on_physical = {vertex_id for edge in physical_edge_keys for vertex_id in edge}
    transit_ids = tuple(
        sorted(carrier_on_physical - set(design.core_ids) - set(design.aggregation_ids))
    )
    return Design(
        core_ids=design.core_ids,
        aggregation_ids=design.aggregation_ids,
        transit_ids=transit_ids,
        access_edges=design.access_edges,
        physical_edge_keys=physical_edge_keys,
        path_uses=design.path_uses,
        metrics=DesignMetrics(
            design.metrics.score,
            design.metrics.access_miles,
            design.metrics.physical_miles,
        ),
    )

def refresh_physical_costs(
    physical_edges: dict[tuple[str, str], PhysicalEdge], design: Design
) -> Design:
    """Recompute physical mileage and score after the edge set changed."""
    design.metrics.physical_miles = sum(
        physical_edges[key].distance_miles for key in design.physical_edge_keys
    )
    design.metrics.score = design.metrics.access_miles + design.metrics.physical_miles
    return design

def best_edge_to_add(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    current: Design,
    current_badness: tuple[int, int, int],
) -> tuple[tuple[str, str] | None, tuple[int, int, int]]:
    """Find the unused physical edge that most reduces design badness."""
    best_key: tuple[str, str] | None = None
    best_rank: tuple[int, int, int, float, tuple[str, str]] | None = None
    best_badness = current_badness
    for key, edge in physical_edges.items():
        if key in current.physical_edge_keys:
            continue
        candidate = with_updated_physical_edges(
            current, current.physical_edge_keys | {key}
        )
        candidate_badness = design_badness(vertices, candidate)
        if candidate_badness >= current_badness:
            continue
        gain = tuple(
            before - after for before, after in zip(current_badness, candidate_badness)
        )
        rank = (-gain[0], -gain[1], -gain[2], edge.distance_miles, key)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best_key = key
            best_badness = candidate_badness
    return best_key, best_badness

def augment_physical_resilience(
    vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
    design: Design,
) -> Design:
    """Greedily add physical edges to remove cut vertices and degree deficits."""
    current = with_updated_physical_edges(design, set(design.physical_edge_keys))
    current_badness = design_badness(vertices, current)

    while current_badness != (0, 0, 0):
        best_key, best_badness = best_edge_to_add(
            vertices, physical_edges, current, current_badness
        )
        if best_key is None:
            break
        current = with_updated_physical_edges(
            current, current.physical_edge_keys | {best_key}
        )
        current_badness = best_badness

    return refresh_physical_costs(physical_edges, current)

def selected_physical_adjacency(design: Design) -> dict[str, list[tuple[str, float]]]:
    """Unit-weight adjacency over only the physical edges the design selected."""
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for left, right in design.physical_edge_keys:
        adjacency.setdefault(left, []).append((right, 1.0))
        adjacency.setdefault(right, []).append((left, 1.0))
    return adjacency

def aggregations_without_core_redundancy(design: Design) -> list[str]:
    """Aggregations lacking two vertex-disjoint paths to two distinct cores."""
    adjacency = selected_physical_adjacency(design)
    missing: list[str] = []
    for aggregation_id in design.aggregation_ids:
        _distance, paths = vertex_disjoint_paths_to_cores(
            adjacency, aggregation_id, design.core_ids, 2
        )
        if len(paths) < 2:
            missing.append(aggregation_id)
    return missing

def disconnected_core_pairs(design: Design) -> list[tuple[str, str]]:
    """Core pairs that are not connected over the selected physical edges."""
    adjacency = selected_physical_adjacency(design)
    disconnected: list[tuple[str, str]] = []
    for left, right in itertools.combinations(design.core_ids, 2):
        if left not in adjacency:
            disconnected.append((left, right))
            continue
        distances, _predecessors = dijkstra(adjacency, left)
        if right not in distances:
            disconnected.append((left, right))
    return disconnected

def core_backbone_pairs(design: Design) -> set[tuple[str, str]]:
    """The logical core-to-core backbone links, one per ``core_mesh`` path use."""
    return {
        edge_key(use.source, use.target)
        for use in design.path_uses
        if use.purpose == "core_mesh"
    }

def core_backbone_two_edge_connected(design: Design) -> bool:
    """True if the core backbone connects every core and survives any single link loss."""
    ids = set(design.core_ids)
    if len(ids) < 2:
        return True
    return is_two_edge_connected(ids, core_backbone_pairs(design))

def neighbor_degrees(
    ids: set[str], edges: set[tuple[str, str]]
) -> dict[str, int]:
    """Distinct-neighbor degree of every included vertex in the design graph."""
    neighbors: dict[str, set[str]] = {vertex_id: set() for vertex_id in ids}
    for left, right in edges:
        if left in ids and right in ids:
            neighbors[left].add(right)
            neighbors[right].add(left)
    return {vertex_id: len(value) for vertex_id, value in neighbors.items()}

def access_attachment_counts(design: Design) -> dict[str, int]:
    """Number of aggregation links attached to each access vertex."""
    counts: dict[str, int] = {}
    for edge in design.access_edges:
        counts[edge.source] = counts.get(edge.source, 0) + 1
    return counts

def validate_design(vertices: list[Vertex], design: Design) -> ValidationReport:
    """Check a design against every hard structural requirement."""
    vertices_by_id = {vertex.id: vertex for vertex in vertices}
    ids = included_vertex_ids(design)
    edges = design_edge_set(design)
    components = connected_components(ids, edges)
    degrees = neighbor_degrees(ids, edges)
    articulations = articulation_points(ids, edges) if len(components) == 1 else set()
    attachments = access_attachment_counts(design)
    missing_core_redundancy = aggregations_without_core_redundancy(design)
    core_pairs = disconnected_core_pairs(design)
    backbone_degrees = neighbor_degrees(set(design.core_ids), core_backbone_pairs(design))
    backbone_deficient = backbone_degree_deficient(
        design.core_ids, backbone_degrees, vertices_by_id
    )

    return {
        "connected": len(components) == 1,
        "component_count": len(components),
        "min_distinct_neighbor_degree": min(degrees.values()) if degrees else 0,
        "degree_deficient_vertices": [
            {"id": vertex_id, "name": vertices_by_id[vertex_id].name, "degree": degree}
            for vertex_id, degree in sorted(degrees.items())
            if degree < 2
        ],
        "biconnected_no_articulation_points": len(components) == 1 and not articulations,
        "articulation_points": [
            {"id": vertex_id, "name": vertices_by_id[vertex_id].name}
            for vertex_id in sorted(articulations)
        ],
        "access_vertices_with_two_aggregation_links": all(
            count == 2 for count in attachments.values()
        ),
        "aggregations_dual_homed_to_cores": not missing_core_redundancy,
        "aggregations_missing_core_redundancy": [
            {"id": vertex_id, "name": vertices_by_id[vertex_id].name}
            for vertex_id in missing_core_redundancy
        ],
        "cores_full_mesh": not core_pairs,
        "core_pairs_disconnected": [
            {"source": vertices_by_id[left].name, "target": vertices_by_id[right].name}
            for left, right in core_pairs
        ],
        "core_backbone_min_degree": min(backbone_degrees.values(), default=0),
        "cores_connect_to_three_others": not backbone_deficient,
        "core_backbone_degree_deficient": backbone_deficient,
        "core_backbone_two_edge_connected": core_backbone_two_edge_connected(design),
    }

def vertex_role(vertex_id: str, design: Design, vertex: Vertex) -> str:
    """Return the tier role (access/core/aggregation/transit/unused) of a vertex."""
    if not is_carrier_pop(vertex):
        return "access"
    if vertex_id in design.core_ids:
        return "core"
    if vertex_id in design.aggregation_ids:
        return "aggregation"
    if vertex_id in design.transit_ids:
        return "transit"
    return "unused"
