"""Unit tests for the design validation checks.

The two requirements under test: every aggregation must reach two distinct cores
over vertex-disjoint paths, and the core tier must form a connected full mesh.
"""

from __future__ import annotations

from wan_designer import (
    Design,
    DesignMetrics,
    PathUse,
    ValidationReport,
    Vertex,
    aggregations_without_core_redundancy,
    disconnected_core_pairs,
    edge_key,
    validate_design,
)


def make_pop(vertex_id: str) -> Vertex:
    """Test helper: build make pop."""
    return Vertex(
        id=vertex_id, name=vertex_id, tenant="Lumen",
        kind="PoP", coords=(0.0, 0.0),
    )


def build_design(
    core_ids: tuple[str, ...],
    aggregation_ids: tuple[str, ...],
    transit_ids: tuple[str, ...],
    physical_pairs: list[tuple[str, str]],
) -> Design:
    """Test helper: build build design."""
    return Design(
        core_ids=core_ids,
        aggregation_ids=aggregation_ids,
        transit_ids=transit_ids,
        access_edges=[],
        physical_edge_keys={edge_key(left, right) for left, right in physical_pairs},
        path_uses=[],
        metrics=DesignMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
    )


# A diamond: aggregation A reaches C1 via X and C2 via Y, plus a core mesh link.
GOOD = build_design(
    core_ids=("C1", "C2"),
    aggregation_ids=("A",),
    transit_ids=("X", "Y"),
    physical_pairs=[("A", "X"), ("X", "C1"), ("A", "Y"), ("Y", "C2"), ("C1", "C2")],
)

# Aggregation A reaches both cores only through the single transit vertex Z.
BOTTLENECK = build_design(
    core_ids=("C1", "C2"),
    aggregation_ids=("A",),
    transit_ids=("Z",),
    physical_pairs=[("A", "Z"), ("Z", "C1"), ("Z", "C2"), ("C1", "C2")],
)

# Three cores but C3 is isolated from the rest of the selected fabric.
BROKEN_MESH = build_design(
    core_ids=("C1", "C2", "C3"),
    aggregation_ids=(),
    transit_ids=(),
    physical_pairs=[("C1", "C2"), ("C3", "Q")],
)

GOOD_VERTICES = [make_pop(name) for name in ("A", "X", "Y", "C1", "C2")]
BOTTLENECK_VERTICES = [make_pop(name) for name in ("A", "Z", "C1", "C2")]
BROKEN_MESH_VERTICES = [make_pop(name) for name in ("C1", "C2", "C3", "Q")]


def test_good_design_is_dual_homed() -> None:
    """Good design is dual homed."""
    assert validate_design(GOOD_VERTICES, GOOD)["aggregations_dual_homed_to_cores"] is True


def test_good_design_has_full_mesh() -> None:
    """Good design has full mesh."""
    assert validate_design(GOOD_VERTICES, GOOD)["cores_full_mesh"] is True


def test_good_design_has_no_missing_redundancy() -> None:
    """Good design has no missing redundancy."""
    assert not aggregations_without_core_redundancy(GOOD)


def test_bottleneck_is_not_dual_homed() -> None:
    """Bottleneck is not dual homed."""
    report = validate_design(BOTTLENECK_VERTICES, BOTTLENECK)
    assert report["aggregations_dual_homed_to_cores"] is False


def test_bottleneck_names_the_failing_aggregation() -> None:
    """Bottleneck names the failing aggregation."""
    assert aggregations_without_core_redundancy(BOTTLENECK) == ["A"]


def test_broken_mesh_is_not_full_mesh() -> None:
    """Broken mesh is not full mesh."""
    report = validate_design(BROKEN_MESH_VERTICES, BROKEN_MESH)
    assert report["cores_full_mesh"] is False


def test_broken_mesh_reports_disconnected_pairs() -> None:
    """Broken mesh reports disconnected pairs."""
    pairs = disconnected_core_pairs(BROKEN_MESH)
    assert ("C1", "C3") in pairs and ("C2", "C3") in pairs


def _backbone_design(core_ids: tuple[str, ...], pairs: list[tuple[str, str]]) -> Design:
    """A design whose only routes are the given core-to-core backbone links."""
    return Design(
        core_ids=core_ids,
        aggregation_ids=(),
        transit_ids=(),
        access_edges=[],
        physical_edge_keys={edge_key(left, right) for left, right in pairs},
        path_uses=[
            PathUse("core_mesh", left, right, (left, right), 1.0) for left, right in pairs
        ],
        metrics=DesignMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
    )


def _backbone_report(core_ids: tuple[str, ...], pairs: list[tuple[str, str]]) -> ValidationReport:
    """Validate a core-only design defined by its backbone links."""
    return validate_design(
        [make_pop(name) for name in core_ids], _backbone_design(core_ids, pairs)
    )


# Five cores each wired to at least three others: a 5-cycle plus three chords.
_HEALTHY = (
    ("C1", "C2", "C3", "C4", "C5"),
    [("C1", "C2"), ("C2", "C3"), ("C3", "C4"), ("C4", "C5"), ("C5", "C1"),
     ("C1", "C3"), ("C2", "C4"), ("C3", "C5")],
)
# Five cores wired so C3, C4, and C5 keep only two backbone links -- below the floor.
_DEFICIENT = (
    ("C1", "C2", "C3", "C4", "C5"),
    [("C1", "C2"), ("C1", "C3"), ("C1", "C4"), ("C2", "C4"), ("C2", "C5"), ("C3", "C5")],
)
# Three cores cannot reach a floor of three, so the connect-to-three rule is moot.
_SMALL = (("C1", "C2", "C3"), [("C1", "C2"), ("C2", "C3"), ("C1", "C3")])


def test_backbone_meeting_the_floor_satisfies_the_connect_rule() -> None:
    """Five cores each wired to three or more others satisfy the connect-to-three rule."""
    assert _backbone_report(*_HEALTHY)["cores_connect_to_three_others"] is True


def test_backbone_reports_its_minimum_degree() -> None:
    """The report's min backbone degree reflects the least-connected core's links."""
    assert _backbone_report(*_HEALTHY)["core_backbone_min_degree"] == 3


def test_backbone_below_the_floor_fails_the_connect_rule() -> None:
    """Cores left with only two backbone links fail the connect-to-three rule."""
    assert _backbone_report(*_DEFICIENT)["cores_connect_to_three_others"] is False


def test_backbone_below_the_floor_names_the_deficient_cores() -> None:
    """The deficient list names every core left under three backbone links."""
    report = _backbone_report(*_DEFICIENT)
    assert {item["id"] for item in report["core_backbone_degree_deficient"]} == {"C3", "C4", "C5"}


def test_three_cores_are_exempt_from_the_connect_rule() -> None:
    """With only three cores the connect-to-three rule cannot apply, so it passes."""
    assert _backbone_report(*_SMALL)["cores_connect_to_three_others"] is True


def test_healthy_backbone_is_two_edge_connected() -> None:
    """A backbone that survives any single link loss is reported resilient."""
    assert _backbone_report(*_HEALTHY)["core_backbone_two_edge_connected"] is True


def test_bridged_backbone_is_not_two_edge_connected() -> None:
    """A backbone with a bridge (a chain) is flagged as not 2-edge-connected."""
    chain = _backbone_design(("C1", "C2", "C3"), [("C1", "C2"), ("C2", "C3")])
    report = validate_design([make_pop(n) for n in ("C1", "C2", "C3")], chain)
    assert report["core_backbone_two_edge_connected"] is False
