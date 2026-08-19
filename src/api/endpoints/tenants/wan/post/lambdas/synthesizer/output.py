"""Build the synthesis payload the REST API serves to the browser."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

from synthesizer.codec import PROVIDER_KIND
from synthesizer.collections import vertex_role
from synthesizer.input_graph import Vertex, edge_key
from synthesizer.model import Synthesis, SynthesisArtifacts, SourceFiles, is_carrier_pop
from synthesizer.validation import included_vertex_ids


def sorted_physical_edges(synthesis: Synthesis) -> list[tuple[str, str]]:
    """Return the synthesis's physical edge keys in sorted order."""
    return sorted(synthesis.physical_edge_keys)


def included_demand_count(vertices: Iterable[Vertex], synthesis: Synthesis) -> int:
    """Count demand vertices actually homed into the synthesis.

    Mirrors the synthesis-membership semantics of the backbone count: a demand vertex
    only counts once it is homed to a backbone node (i.e. it appears in
    :func:`included_vertex_ids`), not merely because it was loaded as demand.
    """
    included = included_vertex_ids(synthesis)
    return sum(
        1 for vertex in vertices if not is_carrier_pop(vertex) and vertex.id in included
    )


def _demand_edge_kind(source_vertex: Vertex) -> str:
    """Label a demand-to-backbone access edge by its source vertex kind."""
    return "provider_to_backbone" if source_vertex.kind == PROVIDER_KIND else "tenant_to_backbone"


def synthesis_payload(sources: SourceFiles, artifacts: SynthesisArtifacts) -> dict[str, Any]:
    """Build the full synthesis, vertices, edges, and validation report as a dict.

    This is the single serialization the REST API slices into its atomic
    endpoints, so the frontend consumes one coherent synthesis computation.
    """
    vertices = artifacts.vertices
    physical_edges = artifacts.physical_edges
    synthesis = artifacts.synthesis
    validation = artifacts.validation
    vertices_by_id = {vertex.id: vertex for vertex in vertices}
    return {
        "vertices_files": [str(path) for path in sources.vertex_files],
        "physical_edge_file": str(sources.edge_path),
        "objective": (
            "Two-tier WAN synthesis: demand vertices (tenant sites and provider regions) home "
            "to a meshed backbone of selected Carrier PoPs over the physical Carrier "
            "graph, with at least three strong backbone nodes and extra ones added "
            "where they bring demand closer."
        ),
        "summary": {
            "backbone_count": len(synthesis.backbone_ids),
            "transit_count": len(synthesis.transit_ids),
            "demand_vertex_count": included_demand_count(vertices, synthesis),
            "access_edge_count": len(synthesis.access_edges),
            "physical_edge_count": len(synthesis.physical_edge_keys),
            "access_miles": round(synthesis.metrics.access_miles, 3),
            "physical_carrier_miles": round(synthesis.metrics.physical_miles, 3),
            # The fewest fiber miles any backbone meeting this tenant's requirements could
            # have run (see :mod:`synthesizer.survivable`). It sits beside the miles the
            # synthesis actually ordered because the two are only meaningful together: a
            # figure for what was bought says nothing about whether it was worth buying
            # until there is a figure for what the same requirements could have cost.
            "backbone_lower_bound_miles": round(
                synthesis.metrics.backbone_lower_bound_miles, 3
            ),
            "total_synthesis_miles": round(
                synthesis.metrics.access_miles + synthesis.metrics.physical_miles, 3
            ),
            "score": round(synthesis.metrics.score, 3),
            "backbone_nodes": [
                vertices_by_id[vertex_id].name for vertex_id in synthesis.backbone_ids
            ],
        },
        "validation": validation,
        "vertices": [
            {
                **asdict(vertex),
                "tier_role": vertex_role(vertex, synthesis),
                "included": vertex.id in included_vertex_ids(synthesis),
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
            for edge in sorted(synthesis.access_edges, key=lambda item: (item.source, item.target))
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
            for left, right in sorted_physical_edges(synthesis)
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
                "reason": path_use.reason,
                "requested_by": [
                    vertices_by_id[vertex_id].name for vertex_id in path_use.requested_by
                ],
            }
            for path_use in synthesis.path_uses
        ],
    }
