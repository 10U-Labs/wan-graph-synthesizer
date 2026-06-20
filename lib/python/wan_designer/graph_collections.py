"""Per-collection JSON views of a graph, shared by the read endpoints and create tasks.

For a computed customer WAN, slice the single ``design_payload`` (output.py) into its
collections (vertices, edges, the tier views). For an input graph (carrier / CSP /
substrate), shape its raw vertices and carrier edges directly.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from wan_designer.model import PhysicalEdge, Vertex, VertexInfo, edge_key


def vertices(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The vertices of a computed customer WAN (each carries kind + tier_role)."""
    result: list[dict[str, Any]] = payload["vertices"]
    return result


def edges(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every edge of a computed customer WAN: access homings plus carrier fiber."""
    result: list[dict[str, Any]] = payload["access_edges"] + payload["physical_edges"]
    return result


def _tier(payload: dict[str, Any], tier_role: str) -> list[dict[str, Any]]:
    return [vertex for vertex in payload["vertices"] if vertex["tier_role"] == tier_role]


def core_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The carrier PoPs the design selected as core (national) hubs."""
    return _tier(payload, "core")


def aggregation_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The carrier PoPs the design selected as aggregation (regional) hubs."""
    return _tier(payload, "aggregation")


def access_nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The demand vertices (installations + CSP regions) homed into the design."""
    return _tier(payload, "access")


def _load_vertex(vertex: dict[str, Any]) -> Vertex:
    """Rebuild one ``Vertex`` (with its ``VertexInfo``) from serialized JSON."""
    coords = vertex["coords"]
    return Vertex(
        id=vertex["id"],
        name=vertex["name"],
        tenant=vertex["tenant"],
        kind=vertex["kind"],
        coords=(float(coords[0]), float(coords[1])),
        info=VertexInfo(**vertex["info"]),
        shown_in_map=vertex["shown_in_map"],
    )


def load_input_graph(
    payload: dict[str, Any],
) -> tuple[list[Vertex], dict[tuple[str, str], PhysicalEdge]]:
    """Rebuild a graph's vertices and physical edges from its stored JSON.

    The inverse of :func:`input_graph`: the ``Vertex`` and ``PhysicalEdge``
    dataclasses are reconstructed so the stored substrate can feed the optimizer.
    """
    loaded_vertices = [_load_vertex(vertex) for vertex in payload["vertices"]]
    loaded_edges: dict[tuple[str, str], PhysicalEdge] = {}
    for edge in payload["edges"]:
        loaded_edges[edge_key(edge["source_id"], edge["target_id"])] = PhysicalEdge(
            source=edge["source_id"],
            target=edge["target_id"],
            distance_miles=edge["distance_miles"],
            source_page=edge["source_page"],
            note=edge["note"],
        )
    return loaded_vertices, loaded_edges


def input_graph(
    graph_vertices: list[Vertex],
    physical_edges: dict[tuple[str, str], PhysicalEdge],
) -> dict[str, list[dict[str, Any]]]:
    """Shape an input graph (carrier / CSP / substrate) as vertices + edges JSON.

    CSP inputs have no fiber edges, so ``edges`` is empty for them.
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
