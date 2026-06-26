"""Validate a design against the hard resilience requirements."""

from __future__ import annotations

from synthesizer.input_graph import Vertex, edge_key
from synthesizer.model import Design, ValidationReport
from synthesizer.graphs import (
    articulation_points,
    connected_components,
    is_two_edge_connected,
    path_edge_keys,
)


# Every backbone node must link to at least ``mesh_degree`` other backbone nodes --
# but only once the backbone is larger than that target, since fewer nodes cannot
# reach it.


def backbone_mesh_deficient(
    backbone_ids: tuple[str, ...],
    backbone_degrees: dict[str, int],
    vertices_by_id: dict[str, Vertex],
    mesh_degree: int,
) -> list[dict[str, object]]:
    """Backbone nodes with fewer than ``mesh_degree`` mesh links.

    With ``mesh_degree`` or fewer backbone nodes the target cannot be met (a node has
    only that many peers), so the list is empty.
    """
    if len(backbone_ids) <= mesh_degree:
        return []
    return [
        {"id": backbone_id, "name": vertices_by_id[backbone_id].name, "degree": degree}
        for backbone_id, degree in sorted(backbone_degrees.items())
        if degree < mesh_degree
    ]


def design_edge_set(design: Design) -> set[tuple[str, str]]:
    """All edges in the design: selected physical edges plus access edges."""
    edges = set(design.physical_edge_keys)
    edges.update(edge_key(edge.source, edge.target) for edge in design.access_edges)
    return edges

def included_vertex_ids(design: Design) -> set[str]:
    """Every vertex id that participates in the design."""
    ids = set(design.backbone_ids) | set(design.transit_ids)
    ids.update(vertex_id for edge in design.physical_edge_keys for vertex_id in edge)
    ids.update(edge.source for edge in design.access_edges)
    ids.update(edge.target for edge in design.access_edges)
    return ids

def demand_backbone_homes(design: Design) -> dict[str, set[str]]:
    """The distinct backbone nodes each demand vertex homes to, by access edges."""
    homes: dict[str, set[str]] = {}
    for edge in design.access_edges:
        homes.setdefault(edge.source, set()).add(edge.target)
    return homes

def demand_without_backbone_redundancy(design: Design, homes: int) -> list[str]:
    """Demand vertices homing to a number of distinct backbone nodes other than ``homes``.

    The requirement is exact, not a floor: every demand vertex homes to exactly ``homes``
    backbone nodes, so both too few and too many are flagged.
    """
    return [
        demand_id
        for demand_id, targets in sorted(demand_backbone_homes(design).items())
        if len(targets) != homes
    ]

def backbone_mesh_pairs(design: Design) -> set[tuple[str, str]]:
    """The logical backbone-to-backbone mesh links, one per ``backbone_mesh`` path use."""
    return {
        edge_key(use.source, use.target)
        for use in design.path_uses
        if use.purpose == "backbone_mesh"
    }

def backbone_mesh_physical_spans(design: Design) -> set[tuple[str, str]]:
    """The physical fiber spans the backbone mesh actually routes over.

    The union of every ``backbone_mesh`` path's spans -- the real cables, not the logical
    city-pairs, so two links sharing a corridor count that corridor once.
    """
    spans: set[tuple[str, str]] = set()
    for use in design.path_uses:
        if use.purpose == "backbone_mesh":
            spans |= path_edge_keys(use.path)
    return spans

def backbone_mesh_two_edge_connected(design: Design) -> bool:
    """True if the backbone's physical fiber survives the loss of any single span.

    Tested over the spans the mesh routes over, not the logical pairs: two logical links
    that ride one corridor offer no real redundancy, so the check must see the cables. A
    backbone node with no routed span reads as disconnected.
    """
    ids = set(design.backbone_ids)
    if len(ids) < 2:
        return True
    spans = backbone_mesh_physical_spans(design)
    vertices = ids | {vertex for span in spans for vertex in span}
    return is_two_edge_connected(vertices, spans)

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

def validate_design(
    vertices: list[Vertex],
    design: Design,
    access_backbone_links: int = 2,
    backbone_mesh_degree: int = 3,
) -> ValidationReport:
    """Check a design against every hard structural requirement.

    ``access_backbone_links`` is the exact number of backbone nodes each demand vertex
    must home to; ``backbone_mesh_degree`` is the number of other backbone nodes
    each backbone node must link to on the mesh. Both are the operator's configured
    redundancy levels.
    """
    vertices_by_id = {vertex.id: vertex for vertex in vertices}
    ids = included_vertex_ids(design)
    edges = design_edge_set(design)
    components = connected_components(ids, edges)
    degrees = neighbor_degrees(ids, edges)
    articulations = articulation_points(ids, edges) if len(components) == 1 else set()
    missing_redundancy = demand_without_backbone_redundancy(design, access_backbone_links)
    backbone_degrees = neighbor_degrees(set(design.backbone_ids), backbone_mesh_pairs(design))
    mesh_deficient = backbone_mesh_deficient(
        design.backbone_ids, backbone_degrees, vertices_by_id, backbone_mesh_degree
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
        "access_vertices_with_required_backbone_links": not missing_redundancy,
        "demand_missing_backbone_redundancy": [
            {"id": vertex_id, "name": vertices_by_id[vertex_id].name}
            for vertex_id in missing_redundancy
        ],
        "backbone_meets_mesh_link_target": not mesh_deficient,
        "backbone_mesh_degree_deficient": mesh_deficient,
        "backbone_mesh_two_edge_connected": backbone_mesh_two_edge_connected(design),
    }
