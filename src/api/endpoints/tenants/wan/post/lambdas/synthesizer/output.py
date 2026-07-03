"""Build the design payload the REST API serves to the browser."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from synthesizer.codec import PROVIDER_KIND
from synthesizer.collections import vertex_role
from synthesizer.input_graph import Vertex, edge_key
from synthesizer.model import Design, DesignArtifacts, SourceFiles, is_carrier_pop
from synthesizer.validation import included_vertex_ids


def sorted_physical_edges(design: Design) -> list[tuple[str, str]]:
    """Return the design's physical edge keys in sorted order."""
    return sorted(design.physical_edge_keys)


def included_demand_count(vertices: Iterable[Vertex], design: Design) -> int:
    """Count demand vertices actually homed into the design.

    Mirrors the design-membership semantics of the backbone count: a demand vertex
    only counts once it is homed to a backbone node (i.e. it appears in
    :func:`included_vertex_ids`), not merely because it was loaded as demand.
    """
    included = included_vertex_ids(design)
    return sum(
        1 for vertex in vertices if not is_carrier_pop(vertex) and vertex.id in included
    )


def _demand_edge_kind(source_vertex: Vertex) -> str:
    """Label a demand-to-backbone access edge by its source vertex kind."""
    return "provider_to_backbone" if source_vertex.kind == PROVIDER_KIND else "tenant_to_backbone"


def design_payload(sources: SourceFiles, artifacts: DesignArtifacts) -> dict[str, Any]:
    """Build the full design, vertices, edges, and validation report as a dict.

    This is the single serialization the REST API slices into its atomic
    endpoints, so the frontend consumes one coherent design computation.
    """
    vertices = artifacts.vertices
    physical_edges = artifacts.physical_edges
    design = artifacts.design
    validation = artifacts.validation
    vertices_by_id = {vertex.id: vertex for vertex in vertices}
    return {
        "vertices_files": [str(path) for path in sources.vertex_files],
        "physical_edge_file": str(sources.edge_path),
        "objective": (
            "Two-tier WAN design: demand vertices (tenant sites and provider regions) home "
            "to a meshed backbone of selected Carrier PoPs over the physical Carrier "
            "graph, with at least three strong backbone nodes and extra ones added "
            "where they bring demand closer."
        ),
        "summary": {
            "backbone_count": len(design.backbone_ids),
            "transit_count": len(design.transit_ids),
            "demand_vertex_count": included_demand_count(vertices, design),
            "access_edge_count": len(design.access_edges),
            "physical_edge_count": len(design.physical_edge_keys),
            "access_miles": round(design.metrics.access_miles, 3),
            "physical_carrier_miles": round(design.metrics.physical_miles, 3),
            "total_design_miles": round(
                design.metrics.access_miles + design.metrics.physical_miles, 3
            ),
            "score": round(design.metrics.score, 3),
            "backbone_nodes": [
                vertices_by_id[vertex_id].name for vertex_id in design.backbone_ids
            ],
        },
        "validation": validation,
        "vertices": [
            {
                **asdict(vertex),
                "tier_role": vertex_role(vertex, design),
                "included": vertex.id in included_vertex_ids(design),
            }
            for vertex in vertices
        ],
        "access_edges": [
            {
                "source_id": edge.source,
                "source_name": vertices_by_id[edge.source].name,
                "target_id": edge.target,
                "target_name": vertices_by_id[edge.target].name,
                "edge_kind": _demand_edge_kind(vertices_by_id[edge.source]),
                "distance_miles": round(edge.distance_miles, 3),
            }
            for edge in sorted(design.access_edges, key=lambda item: (item.source, item.target))
        ],
        "physical_edges": [
            {
                "source_id": left,
                "source_name": vertices_by_id[left].name,
                "target_id": right,
                "target_name": vertices_by_id[right].name,
                "edge_kind": "carrier_physical",
                "distance_miles": round(physical_edges[edge_key(left, right)].distance_miles, 3),
                "source_page": physical_edges[edge_key(left, right)].source_page,
                "note": physical_edges[edge_key(left, right)].note,
            }
            for left, right in sorted_physical_edges(design)
        ],
        "path_uses": [
            {
                "purpose": path_use.purpose,
                "source_id": path_use.source,
                "source_name": vertices_by_id[path_use.source].name,
                "target_id": path_use.target,
                "target_name": vertices_by_id[path_use.target].name,
                "distance_miles": round(path_use.distance_miles, 3),
                "path": [vertices_by_id[vertex_id].name for vertex_id in path_use.path],
            }
            for path_use in design.path_uses
        ],
    }
