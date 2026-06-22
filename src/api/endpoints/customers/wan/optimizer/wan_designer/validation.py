"""Validate a design against the hard resilience requirements."""

from __future__ import annotations

from wan_graph.model import Vertex, edge_key
from wan_designer.model import Design, ValidationReport, is_carrier_pop
from wan_designer.graphs import (
    articulation_points,
    connected_components,
    is_two_edge_connected,
    vertex_disjoint_paths_to_cores,
)


# Every core must link to at least ``core_links_per_core`` other cores -- but only
# once the core tier is larger than that target, since fewer cores cannot reach it.


def backbone_degree_deficient(
    core_ids: tuple[str, ...],
    backbone_degrees: dict[str, int],
    vertices_by_id: dict[str, Vertex],
    links_per_core: int,
) -> list[dict[str, object]]:
    """Cores with fewer than ``links_per_core`` backbone links.

    With ``links_per_core`` or fewer cores the target cannot be met (a core has only
    that many peers), so the list is empty.
    """
    if len(core_ids) <= links_per_core:
        return []
    return [
        {"id": core_id, "name": vertices_by_id[core_id].name, "degree": degree}
        for core_id, degree in sorted(backbone_degrees.items())
        if degree < links_per_core
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

def selected_physical_adjacency(design: Design) -> dict[str, list[tuple[str, float]]]:
    """Unit-weight adjacency over only the physical edges the design selected."""
    adjacency: dict[str, list[tuple[str, float]]] = {}
    for left, right in design.physical_edge_keys:
        adjacency.setdefault(left, []).append((right, 1.0))
        adjacency.setdefault(right, []).append((left, 1.0))
    return adjacency

def aggregations_without_core_redundancy(design: Design, homes: int) -> list[str]:
    """Aggregations lacking vertex-disjoint paths to ``homes`` distinct cores."""
    adjacency = selected_physical_adjacency(design)
    missing: list[str] = []
    for aggregation_id in design.aggregation_ids:
        _distance, paths = vertex_disjoint_paths_to_cores(
            adjacency, aggregation_id, design.core_ids, homes
        )
        if len(paths) < homes:
            missing.append(aggregation_id)
    return missing

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

def validate_design(
    vertices: list[Vertex],
    design: Design,
    access_aggregation_links: int = 2,
    core_links_per_core: int = 3,
    aggregation_homing_degree: int = 2,
) -> ValidationReport:
    """Check a design against every hard structural requirement.

    ``access_aggregation_links`` is the number of aggregation facilities each access
    vertex is required to home to; ``aggregation_homing_degree`` is the number of
    distinct cores each aggregation must reach over vertex-disjoint paths;
    ``core_links_per_core`` is the number of other cores each core must link to on the
    backbone. All three are the operator's configured redundancy levels.
    """
    vertices_by_id = {vertex.id: vertex for vertex in vertices}
    ids = included_vertex_ids(design)
    edges = design_edge_set(design)
    components = connected_components(ids, edges)
    degrees = neighbor_degrees(ids, edges)
    articulations = articulation_points(ids, edges) if len(components) == 1 else set()
    attachments = access_attachment_counts(design)
    missing_core_redundancy = aggregations_without_core_redundancy(
        design, aggregation_homing_degree
    )
    backbone_degrees = neighbor_degrees(set(design.core_ids), core_backbone_pairs(design))
    backbone_deficient = backbone_degree_deficient(
        design.core_ids, backbone_degrees, vertices_by_id, core_links_per_core
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
        "access_vertices_with_required_aggregation_links": all(
            count == access_aggregation_links for count in attachments.values()
        ),
        "aggregations_dual_homed_to_cores": not missing_core_redundancy,
        "aggregations_missing_core_redundancy": [
            {"id": vertex_id, "name": vertices_by_id[vertex_id].name}
            for vertex_id in missing_core_redundancy
        ],
        "cores_meet_backbone_link_target": not backbone_deficient,
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
