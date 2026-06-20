"""Per-collection JSON views of a graph, shared by the read endpoints and create tasks.

For a computed customer WAN, slice the single ``design_payload`` (output.py) into its
collections (vertices, edges, the tier views). For an input graph (carrier / provider /
substrate), shape its raw vertices and carrier edges directly.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from wan_designer.model import PhysicalEdge, Vertex


def vertices(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The vertices of a computed customer WAN (each carries kind + tier_role)."""
    return payload["vertices"]


def edges(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every edge of a computed customer WAN: access homings plus carrier fiber."""
    return payload["access_edges"] + payload["physical_edges"]


def _tier(payload: dict[str, Any], tier_role: str) -> list[dict[str, Any]]:
    return [vertex for vertex in payload["vertices"] if vertex["tier_role"] == tier_role]


def core_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The carrier PoPs the design selected as core (national) hubs."""
    return _tier(payload, "core")


def aggregation_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The carrier PoPs the design selected as aggregation (regional) hubs."""
    return _tier(payload, "aggregation")


def access_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The demand vertices (installations + provider regions) homed into the design."""
    return _tier(payload, "access")


def input_graph(
    graph_vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> dict[str, list[dict[str, Any]]]:
    """Shape an input graph (carrier / provider / substrate) as vertices + edges JSON.

    provider inputs have no fiber edges, so ``edges`` is empty for them.
    """
    names = {vertex.id: vertex.name for vertex in graph_vertices}
    return {
        "vertices": [asdict(vertex) for vertex in graph_vertices],
        "edges": [
            {
                "source_id": left,
                "source_name": names[left],
                "target_id": right,
                "target_name": names[right],
                "edge_kind": "carrier_physical",
                "distance_miles": round(edge.distance_miles, 3),
                "source_page": edge.source_page,
                "note": edge.note,
            }
            for (left, right), edge in sorted(physical_edges.items())
        ],
    }
