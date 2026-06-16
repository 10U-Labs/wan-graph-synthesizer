"""Build the design payload the REST API serves to the browser."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from wan_designer.model import (
    Design,
    DesignArtifacts,
    SourceFiles,
    edge_key,
    is_carrier_pop,
)
from wan_designer.validation import included_vertex_ids, vertex_role


def sorted_physical_edges(design: Design) -> list[tuple[str, str]]:
    """Return the design's physical edge keys in sorted order."""
    return sorted(design.physical_edge_keys)

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
            "Three-tier WAN design: access vertices dual-home to Carrier aggregation PoPs, "
            "aggregation PoPs dual-home to core PoPs over the physical Carrier graph, "
            "and the core tier uses at least three strong vertices, with extra cores "
            "added where they bring demand closer."
        ),
        "summary": {
            "core_count": len(design.core_ids),
            "aggregation_count": len(design.aggregation_ids),
            "transit_count": len(design.transit_ids),
            "access_vertex_count": sum(1 for vertex in vertices if not is_carrier_pop(vertex)),
            "access_edge_count": len(design.access_edges),
            "physical_edge_count": len(design.physical_edge_keys),
            "access_miles": round(design.metrics.access_miles, 3),
            "physical_carrier_miles": round(design.metrics.physical_miles, 3),
            "total_design_miles": round(
                design.metrics.access_miles + design.metrics.physical_miles, 3
            ),
            "score": round(design.metrics.score, 3),
            "cores": [vertices_by_id[vertex_id].name for vertex_id in design.core_ids],
            "aggregations": [
                vertices_by_id[vertex_id].name for vertex_id in design.aggregation_ids
            ],
        },
        "validation": validation,
        "vertices": [
            {
                **asdict(vertex),
                "tier_role": vertex_role(vertex.id, design, vertex),
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
                "edge_kind": "access_to_aggregation",
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
