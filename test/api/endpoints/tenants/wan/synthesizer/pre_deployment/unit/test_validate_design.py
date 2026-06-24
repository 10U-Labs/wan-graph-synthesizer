"""Unit tests for the design validation checks.

The two requirements under test: every aggregation must reach two distinct cores
over vertex-disjoint paths, and every core must wire to its configured number of
nearest cores on the backbone.
"""

from __future__ import annotations

from synthesizer.validation import aggregations_without_core_redundancy, validate_design
from synthesizer.model import AccessEdge, Design, DesignMetrics, PathUse, ValidationReport
from synthesizer.input_graph import Vertex, edge_key


def make_pop(vertex_id: str) -> Vertex:
    """Test helper: build make pop."""
    return Vertex(
        id=vertex_id, name=vertex_id,
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

GOOD_VERTICES = [make_pop(name) for name in ("A", "X", "Y", "C1", "C2")]
BOTTLENECK_VERTICES = [make_pop(name) for name in ("A", "Z", "C1", "C2")]


def test_good_design_is_dual_homed() -> None:
    """Good design is dual homed."""
    assert validate_design(GOOD_VERTICES, GOOD)["aggregations_dual_homed_to_cores"] is True


def test_core_backbone_two_edge_connected_with_fewer_than_two_cores() -> None:
    """A backbone with fewer than two cores is trivially two-edge-connected."""
    design = build_design(
        core_ids=("C1",), aggregation_ids=(), transit_ids=(), physical_pairs=[]
    )
    report = validate_design([make_pop("C1")], design)
    assert report["core_backbone_two_edge_connected"] is True


def test_good_design_has_no_missing_redundancy() -> None:
    """Good design has no missing redundancy."""
    assert not aggregations_without_core_redundancy(GOOD, 2)


# An access vertex "s" homed to three aggregations, for the configurable-count check.
TRIPLE_HOMED = Design(
    core_ids=("C1", "C2"),
    aggregation_ids=("A", "B", "D"),
    transit_ids=(),
    access_edges=[AccessEdge("s", target, 1.0) for target in ("A", "B", "D")],
    physical_edge_keys={edge_key("C1", "C2")},
    path_uses=[],
    metrics=DesignMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
)
TRIPLE_HOMED_VERTICES = [make_pop(name) for name in ("s", "A", "B", "D", "C1", "C2")]


def test_access_links_pass_at_the_configured_count() -> None:
    """Access vertices with the configured number of aggregation links pass the check."""
    report = validate_design(TRIPLE_HOMED_VERTICES, TRIPLE_HOMED, access_aggregation_links=3)
    assert report["access_vertices_with_required_aggregation_links"] is True


def test_access_links_fail_below_the_configured_count() -> None:
    """The same triple-homed design fails when only two links are required."""
    report = validate_design(TRIPLE_HOMED_VERTICES, TRIPLE_HOMED, access_aggregation_links=2)
    assert report["access_vertices_with_required_aggregation_links"] is False


def test_bottleneck_is_not_dual_homed() -> None:
    """Bottleneck is not dual homed."""
    report = validate_design(BOTTLENECK_VERTICES, BOTTLENECK)
    assert report["aggregations_dual_homed_to_cores"] is False


def test_bottleneck_names_the_failing_aggregation() -> None:
    """Bottleneck names the failing aggregation."""
    assert aggregations_without_core_redundancy(BOTTLENECK, 2) == ["A"]


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


def _backbone_report(
    core_ids: tuple[str, ...], pairs: list[tuple[str, str]], core_links_per_core: int = 3
) -> ValidationReport:
    """Validate a core-only design defined by its backbone links."""
    return validate_design(
        [make_pop(name) for name in core_ids],
        _backbone_design(core_ids, pairs),
        core_links_per_core=core_links_per_core,
    )


# Five cores each wired to at least three others: a 5-cycle plus three chords.
_HEALTHY = (
    ("C1", "C2", "C3", "C4", "C5"),
    [("C1", "C2"), ("C2", "C3"), ("C3", "C4"), ("C4", "C5"), ("C5", "C1"),
     ("C1", "C3"), ("C2", "C4"), ("C3", "C5")],
)
# Five cores wired so C3, C4, and C5 keep only two backbone links -- below the target.
_DEFICIENT = (
    ("C1", "C2", "C3", "C4", "C5"),
    [("C1", "C2"), ("C1", "C3"), ("C1", "C4"), ("C2", "C4"), ("C2", "C5"), ("C3", "C5")],
)
# Three cores cannot reach a target of three, so the link-target rule is moot.
_SMALL = (("C1", "C2", "C3"), [("C1", "C2"), ("C2", "C3"), ("C1", "C3")])


def test_backbone_meeting_the_target_satisfies_the_link_rule() -> None:
    """Five cores each wired to three or more others meet the three-link target."""
    assert _backbone_report(*_HEALTHY)["cores_meet_backbone_link_target"] is True


def test_backbone_below_the_target_fails_the_link_rule() -> None:
    """Cores left with only two backbone links fail the three-link target."""
    assert _backbone_report(*_DEFICIENT)["cores_meet_backbone_link_target"] is False


def test_link_target_is_configurable() -> None:
    """The same cores meet a lowered target of two links each."""
    assert _backbone_report(*_DEFICIENT, core_links_per_core=2)[
        "cores_meet_backbone_link_target"
    ] is True


def test_backbone_below_the_target_names_the_deficient_cores() -> None:
    """The deficient list names every core left under the three-link target."""
    report = _backbone_report(*_DEFICIENT)
    assert {item["id"] for item in report["core_backbone_degree_deficient"]} == {"C3", "C4", "C5"}


def test_small_core_tier_is_exempt_from_the_link_rule() -> None:
    """With only three cores the three-link target cannot apply, so it passes."""
    assert _backbone_report(*_SMALL)["cores_meet_backbone_link_target"] is True


def test_healthy_backbone_is_two_edge_connected() -> None:
    """A backbone that survives any single link loss is reported resilient."""
    assert _backbone_report(*_HEALTHY)["core_backbone_two_edge_connected"] is True


def test_bridged_backbone_is_not_two_edge_connected() -> None:
    """A backbone with a bridge (a chain) is flagged as not 2-edge-connected."""
    chain = _backbone_design(("C1", "C2", "C3"), [("C1", "C2"), ("C2", "C3")])
    report = validate_design([make_pop(n) for n in ("C1", "C2", "C3")], chain)
    assert report["core_backbone_two_edge_connected"] is False
