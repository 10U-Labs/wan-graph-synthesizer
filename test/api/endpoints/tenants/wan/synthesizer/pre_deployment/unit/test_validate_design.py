"""Unit tests for the design validation checks.

The two requirements under test: every demand vertex must home to exactly the configured
number of distinct backbone nodes, and every backbone node must wire to its configured
number of nearest backbone nodes on the mesh.
"""

from __future__ import annotations

from synthesizer.validation import demand_without_backbone_redundancy, validate_design
from synthesizer.model import AccessEdge, Design, DesignMetrics, PathUse, ValidationReport
from synthesizer.input_graph import Vertex, edge_key


def make_pop(vertex_id: str) -> Vertex:
    """Test helper: build a carrier PoP vertex."""
    return Vertex(id=vertex_id, name=vertex_id, kind="PoP", coords=(0.0, 0.0))


def build_design(
    backbone_ids: tuple[str, ...],
    transit_ids: tuple[str, ...],
    access_edges: list[AccessEdge],
    physical_pairs: list[tuple[str, str]],
) -> Design:
    """Test helper: build a Design from tier ids, access edges, and physical pairs."""
    return Design(
        backbone_ids=backbone_ids,
        transit_ids=transit_ids,
        access_edges=access_edges,
        physical_edge_keys={edge_key(left, right) for left, right in physical_pairs},
        path_uses=[],
        metrics=DesignMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
    )


# A diamond: demand vertex A reaches B1 via X and B2 via Y, plus a backbone mesh link.
GOOD = build_design(
    backbone_ids=("B1", "B2"),
    transit_ids=("X", "Y"),
    access_edges=[AccessEdge("A", "B1", 1.0), AccessEdge("A", "B2", 1.0)],
    physical_pairs=[("X", "B1"), ("Y", "B2"), ("B1", "B2")],
)
# Demand vertex A homes to only one backbone node, so it lacks redundancy.
SINGLE_HOMED = build_design(
    backbone_ids=("B1", "B2"),
    transit_ids=(),
    access_edges=[AccessEdge("A", "B1", 1.0)],
    physical_pairs=[("B1", "B2")],
)

GOOD_VERTICES = [make_pop(name) for name in ("A", "X", "Y", "B1", "B2")]
SINGLE_VERTICES = [make_pop(name) for name in ("A", "B1", "B2")]


def test_good_design_homes_demand_with_redundancy() -> None:
    """A demand vertex homed to two backbone nodes meets the redundancy requirement."""
    report = validate_design(GOOD_VERTICES, GOOD)
    assert report["access_vertices_with_required_backbone_links"] is True


def test_good_design_has_no_missing_redundancy() -> None:
    """A demand vertex homed to two backbone nodes is not flagged as deficient."""
    assert not demand_without_backbone_redundancy(GOOD, 2)


def test_backbone_mesh_two_edge_connected_with_fewer_than_two_nodes() -> None:
    """A backbone with fewer than two nodes is trivially two-edge-connected."""
    design = build_design(("B1",), (), [], [])
    report = validate_design([make_pop("B1")], design)
    assert report["backbone_mesh_two_edge_connected"] is True


# A demand vertex "s" homed to three backbone nodes, for the configurable-count check.
TRIPLE_HOMED = build_design(
    backbone_ids=("B1", "B2", "B3"),
    transit_ids=(),
    access_edges=[AccessEdge("s", target, 1.0) for target in ("B1", "B2", "B3")],
    physical_pairs=[("B1", "B2")],
)
TRIPLE_HOMED_VERTICES = [make_pop(name) for name in ("s", "B1", "B2", "B3")]


def test_homing_passes_at_the_configured_count() -> None:
    """Demand homed to the configured number of backbone nodes passes the check."""
    report = validate_design(TRIPLE_HOMED_VERTICES, TRIPLE_HOMED, access_backbone_links=3)
    assert report["access_vertices_with_required_backbone_links"] is True


def test_homing_fails_above_the_configured_count() -> None:
    """Demand homed to more than the configured number of backbone nodes is flagged.

    The homing requirement is exact, so three homes against a configured count of two
    fails just as one home would.
    """
    assert demand_without_backbone_redundancy(TRIPLE_HOMED, 2) == ["s"]


def test_homing_fails_below_the_configured_count() -> None:
    """A single-homed demand vertex fails the two-link redundancy requirement."""
    report = validate_design(SINGLE_VERTICES, SINGLE_HOMED)
    assert report["access_vertices_with_required_backbone_links"] is False


def test_missing_redundancy_names_the_failing_demand_vertex() -> None:
    """The deficiency list names the demand vertex short of its required homes."""
    assert demand_without_backbone_redundancy(SINGLE_HOMED, 2) == ["A"]


def _mesh_design(backbone_ids: tuple[str, ...], pairs: list[tuple[str, str]]) -> Design:
    """A design whose only routes are the given backbone-to-backbone mesh links."""
    return Design(
        backbone_ids=backbone_ids,
        transit_ids=(),
        access_edges=[],
        physical_edge_keys={edge_key(left, right) for left, right in pairs},
        path_uses=[
            PathUse("backbone_mesh", left, right, (left, right), 1.0) for left, right in pairs
        ],
        metrics=DesignMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
    )


def _mesh_report(
    backbone_ids: tuple[str, ...], pairs: list[tuple[str, str]], backbone_mesh_degree: int = 3
) -> ValidationReport:
    """Validate a backbone-only design defined by its mesh links."""
    return validate_design(
        [make_pop(name) for name in backbone_ids],
        _mesh_design(backbone_ids, pairs),
        backbone_mesh_degree=backbone_mesh_degree,
    )


# Five nodes each wired to at least three others: a 5-cycle plus three chords.
_HEALTHY = (
    ("C1", "C2", "C3", "C4", "C5"),
    [("C1", "C2"), ("C2", "C3"), ("C3", "C4"), ("C4", "C5"), ("C5", "C1"),
     ("C1", "C3"), ("C2", "C4"), ("C3", "C5")],
)
# Five nodes wired so C3, C4, and C5 keep only two mesh links -- below the target.
_DEFICIENT = (
    ("C1", "C2", "C3", "C4", "C5"),
    [("C1", "C2"), ("C1", "C3"), ("C1", "C4"), ("C2", "C4"), ("C2", "C5"), ("C3", "C5")],
)
# Three nodes cannot reach a target of three, so the mesh-degree rule is moot.
_SMALL = (("C1", "C2", "C3"), [("C1", "C2"), ("C2", "C3"), ("C1", "C3")])


def test_backbone_meeting_the_target_satisfies_the_mesh_rule() -> None:
    """Five nodes each wired to three or more others meet the three-link target."""
    assert _mesh_report(*_HEALTHY)["backbone_meets_mesh_link_target"] is True


def test_backbone_below_the_target_fails_the_mesh_rule() -> None:
    """Nodes left with only two mesh links fail the three-link target."""
    assert _mesh_report(*_DEFICIENT)["backbone_meets_mesh_link_target"] is False


def test_mesh_degree_is_configurable() -> None:
    """The same nodes meet a lowered target of two links each."""
    assert _mesh_report(*_DEFICIENT, backbone_mesh_degree=2)[
        "backbone_meets_mesh_link_target"
    ] is True


def test_backbone_below_the_target_names_the_deficient_nodes() -> None:
    """The deficient list names every node left under the three-link target."""
    report = _mesh_report(*_DEFICIENT)
    assert {item["id"] for item in report["backbone_mesh_degree_deficient"]} == {"C3", "C4", "C5"}


def test_small_backbone_is_exempt_from_the_mesh_rule() -> None:
    """With only three nodes the three-link target cannot apply, so it passes."""
    assert _mesh_report(*_SMALL)["backbone_meets_mesh_link_target"] is True


def test_healthy_backbone_is_two_edge_connected() -> None:
    """A backbone that survives any single link loss is reported resilient."""
    assert _mesh_report(*_HEALTHY)["backbone_mesh_two_edge_connected"] is True


def test_bridged_backbone_is_not_two_edge_connected() -> None:
    """A backbone with a bridge (a chain) is flagged as not 2-edge-connected."""
    chain = _mesh_design(("C1", "C2", "C3"), [("C1", "C2"), ("C2", "C3")])
    report = validate_design([make_pop(n) for n in ("C1", "C2", "C3")], chain)
    assert report["backbone_mesh_two_edge_connected"] is False


def _routed_design(backbone_ids: tuple[str, ...], path_uses: list[PathUse]) -> Design:
    """A backbone-only design defined directly by its routed physical paths."""
    return Design(
        backbone_ids=backbone_ids,
        transit_ids=(),
        access_edges=[],
        physical_edge_keys=set(),
        path_uses=path_uses,
        metrics=DesignMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
    )


# Logical links A-B and A-C both route over the shared first hop A-X, so the city-pair
# mesh (A-B, A-C, B-C) is a triangle -- logically 2-edge-connected -- while the physical
# fiber hangs A off the lone span A-X. A non-mesh path use rides along, ignored.
_SHARED_CORRIDOR = _routed_design(
    ("A", "B", "C"),
    [
        PathUse("backbone_mesh", "A", "B", ("A", "X", "B"), 2.0),
        PathUse("backbone_mesh", "A", "C", ("A", "X", "C"), 2.0),
        PathUse("backbone_mesh", "B", "C", ("B", "C"), 1.0),
        PathUse("access", "B", "C", ("B", "C"), 1.0),
    ],
)
# Backbone A-B carried over two span-disjoint corridors -- the direct A-B and the detour
# A-Y-B -- so the physical fiber survives the loss of either.
_DISJOINT_PATHS = _routed_design(
    ("A", "B"),
    [
        PathUse("backbone_mesh", "A", "B", ("A", "B"), 1.0),
        PathUse("backbone_mesh", "A", "B", ("A", "Y", "B"), 2.0),
    ],
)


def test_shared_physical_corridor_is_not_two_edge_connected() -> None:
    """Logical links sharing one fiber span offer no real redundancy, so the check fails."""
    report = validate_design([make_pop(n) for n in ("A", "X", "B", "C")], _SHARED_CORRIDOR)
    assert report["backbone_mesh_two_edge_connected"] is False


def test_span_disjoint_paths_are_two_edge_connected() -> None:
    """Two span-disjoint corridors between the backbone nodes survive any single cut."""
    report = validate_design([make_pop(n) for n in ("A", "B", "Y")], _DISJOINT_PATHS)
    assert report["backbone_mesh_two_edge_connected"] is True


# Two disjoint physical edges leave the design graph in two components.
_DISCONNECTED = build_design(
    backbone_ids=("B1", "B2", "B3", "B4"),
    transit_ids=(),
    access_edges=[],
    physical_pairs=[("B1", "B2"), ("B3", "B4")],
)
_DISCONNECTED_VERTICES = [make_pop(name) for name in ("B1", "B2", "B3", "B4")]


def test_disconnected_design_reports_multiple_components() -> None:
    """A design in two pieces is reported with a component count above one."""
    report = validate_design(_DISCONNECTED_VERTICES, _DISCONNECTED)
    assert report["component_count"] == 2


def test_disconnected_design_skips_articulation_search() -> None:
    """With more than one component the design has no articulation points listed."""
    report = validate_design(_DISCONNECTED_VERTICES, _DISCONNECTED)
    assert report["articulation_points"] == []


def test_degree_deficient_vertex_is_named() -> None:
    """A vertex with fewer than two distinct neighbours is named as degree-deficient."""
    report = validate_design(_DISCONNECTED_VERTICES, _DISCONNECTED)
    assert {item["id"] for item in report["degree_deficient_vertices"]} == {
        "B1", "B2", "B3", "B4",
    }


def test_empty_design_reports_zero_min_degree() -> None:
    """A design including no vertices reports a minimum neighbour degree of zero."""
    empty = build_design((), (), [], [])
    assert validate_design([], empty)["min_distinct_neighbor_degree"] == 0


def test_articulation_point_is_flagged() -> None:
    """A cut vertex whose loss splits the design is reported as an articulation point."""
    chain = _mesh_design(("C1", "C2", "C3"), [("C1", "C2"), ("C2", "C3")])
    report = validate_design([make_pop(n) for n in ("C1", "C2", "C3")], chain)
    assert {item["id"] for item in report["articulation_points"]} == {"C2"}
