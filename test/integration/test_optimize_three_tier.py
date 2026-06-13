"""Integration tests for the end-to-end optimizer over a synthetic graph.

A six-PoP ring is 2-connected, so every aggregation can reach two cores over
node-disjoint paths. A degree-one spur hangs off the ring to confirm such PoPs
are never chosen as aggregation points.
"""

from __future__ import annotations

from wan_designer import (
    Design,
    DesignParams,
    Node,
    PhysicalEdge,
    edge_key,
    haversine_miles,
    optimize_three_tier_design,
    validate_design,
)

RING = {
    "P0": (40.0, -100.0),
    "P1": (41.0, -100.0),
    "P2": (41.5, -99.0),
    "P3": (41.0, -98.0),
    "P4": (40.0, -98.0),
    "P5": (39.5, -99.0),
}
SPUR = {"P6": (37.0, -100.0)}
ACCESS = {
    "A1": (41.0, -99.9),
    "A2": (40.0, -98.1),
    "A3": (41.4, -99.1),
}
RING_EDGES = [
    ("P0", "P1"),
    ("P1", "P2"),
    ("P2", "P3"),
    ("P3", "P4"),
    ("P4", "P5"),
    ("P5", "P0"),
    ("P0", "P6"),
]


def pop(node_id: str, lat: float, lon: float) -> Node:
    """Test helper: build pop."""
    return Node(
        id=node_id,
        name=node_id,
        category="Carrier 400G PoPs",
        kind="carrier_pop",
        lat=lat,
        lon=lon,
    )


def access(node_id: str, lat: float, lon: float) -> Node:
    """Test helper: build access."""
    return Node(id=node_id, name=node_id, category="F-35", kind="f35", lat=lat, lon=lon)


def build_nodes() -> list[Node]:
    """Test helper: build build nodes."""
    nodes = [pop(name, lat, lon) for name, (lat, lon) in {**RING, **SPUR}.items()]
    nodes += [access(name, lat, lon) for name, (lat, lon) in ACCESS.items()]
    return nodes


def build_edges(nodes: list[Node]) -> dict[tuple[str, str], PhysicalEdge]:
    """Test helper: build build edges."""
    by_id = {node.id: node for node in nodes}
    edges: dict[tuple[str, str], PhysicalEdge] = {}
    for left, right in RING_EDGES:
        key = edge_key(left, right)
        edges[key] = PhysicalEdge(
            source=key[0],
            target=key[1],
            distance_miles=haversine_miles(by_id[left], by_id[right]),
        )
    return edges


def run() -> tuple[list[Node], Design]:
    """Test helper: build run."""
    nodes = build_nodes()
    edges = build_edges(nodes)
    roles = {node.id: "aggregator" for node in nodes if node.kind == "carrier_pop"}
    params = DesignParams(
        core_count=2, min_core_separation_miles=0.0, core_candidate_limit=10
    )
    design = optimize_three_tier_design(nodes, edges, roles, params)
    return nodes, design


NODES, DESIGN = run()
REPORT = validate_design(NODES, DESIGN)


def test_selects_two_cores() -> None:
    """Selects two cores."""
    assert len(DESIGN.core_ids) == 2


def test_degree_one_spur_is_not_an_aggregation() -> None:
    """Degree one spur is not an aggregation."""
    assert "P6" not in DESIGN.aggregation_ids


def test_degree_one_spur_is_not_a_core() -> None:
    """Degree one spur is not a core."""
    assert "P6" not in DESIGN.core_ids


def test_every_aggregation_dual_homed_to_cores() -> None:
    """Every aggregation dual homed to cores."""
    assert REPORT["aggregations_dual_homed_to_cores"] is True


def test_cores_form_full_mesh() -> None:
    """Cores form full mesh."""
    assert REPORT["cores_full_mesh"] is True


def test_access_nodes_dual_homed() -> None:
    """Access nodes dual homed."""
    assert REPORT["access_nodes_with_two_aggregation_links"] is True


def test_design_is_connected() -> None:
    """Design is connected."""
    assert REPORT["connected"] is True
