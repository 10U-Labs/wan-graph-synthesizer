"""Round-trip tests for input-graph (de)serialization."""

from __future__ import annotations

from wan_graph.graph_collections import input_graph, load_input_graph
from wan_graph.model import PhysicalEdge, Vertex, VertexInfo, edge_key


def _vertex() -> Vertex:
    """A carrier PoP with descriptive info set."""
    return Vertex(
        id="pop1",
        name="Atlanta, GA",
        tenant="Lumen",
        kind="PoP",
        coords=(33.75, -84.39),
        info=VertexInfo(description="d", municipality="Atlanta", state="GA"),
    )


def _edges() -> dict[tuple[str, str], PhysicalEdge]:
    """A single physical edge keyed order-independently."""
    return {
        edge_key("pop1", "pop2"): PhysicalEdge(
            source="pop1", target="pop2", distance_miles=12.5, source_page="p7", note="n"
        )
    }


def test_round_trips_vertices() -> None:
    """A vertex survives input_graph -> load_input_graph unchanged."""
    vertices = [_vertex()]
    loaded, _ = load_input_graph(input_graph(vertices, {}))
    assert loaded == vertices


def test_round_trips_edges() -> None:
    """An edge survives input_graph -> load_input_graph as the same dict."""
    second = Vertex(id="pop2", name="B", tenant="Lumen", kind="PoP", coords=(34.0, -84.0))
    edges = _edges()
    _, loaded = load_input_graph(input_graph([_vertex(), second], edges))
    assert loaded == edges
