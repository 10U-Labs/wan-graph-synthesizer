"""The input-graph JSON codec: the wire-format contract between the two programs.

:func:`input_graph` shapes a graph's vertices and carrier edges as JSON (the inputs
script writes it); :func:`load_input_graph` is its inverse, rebuilding the dataclasses
so the synthesizer can read the stored graph back. Keeping both halves here gives the
on-the-wire format a single definition the writer and reader cannot drift apart from.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from wan_graph.model import PhysicalEdge, Vertex, VertexInfo, edge_key


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
    dataclasses are reconstructed so the stored substrate can feed the synthesizer.
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
