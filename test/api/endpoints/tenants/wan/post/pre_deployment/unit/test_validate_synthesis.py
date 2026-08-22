from __future__ import annotations

import fixtures
from synthesizer.validation import demand_without_backbone_redundancy, validate_synthesis
from synthesizer.model import (
    AccessPath,
    Synthesis,
    SynthesisMetrics,
    MeshRequirements,
    SynthesisPath,
    ValidationReport,
)
from synthesizer.input_graph import Site, link_key


def make_pop(site_id: str) -> Site:
    return Site(id=site_id, name=site_id, kind="PoP", coords=(0.0, 0.0))


def build_synthesis(
    backbone_ids: tuple[str, ...],
    transit_ids: tuple[str, ...],
    access_paths: list[AccessPath],
    physical_pairs: list[tuple[str, str]],
) -> Synthesis:
    return Synthesis(
        backbone_ids=backbone_ids,
        transit_ids=transit_ids,
        access_paths=access_paths,
        fiber_segment_keys={link_key(left, right) for left, right in physical_pairs},
        path_uses=[],
        metrics=SynthesisMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
    )


GOOD = build_synthesis(
    backbone_ids=("B1", "B2"),
    transit_ids=("X", "Y"),
    access_paths=[AccessPath("A", "B1", 1.0), AccessPath("A", "B2", 1.0)],
    physical_pairs=[("X", "B1"), ("Y", "B2"), ("B1", "B2")],
)
SINGLE_HOMED = build_synthesis(
    backbone_ids=("B1", "B2"),
    transit_ids=(),
    access_paths=[AccessPath("A", "B1", 1.0)],
    physical_pairs=[("B1", "B2")],
)

GOOD_SITES = [make_pop(name) for name in ("A", "X", "Y", "B1", "B2")]
SINGLE_SITES = [make_pop(name) for name in ("A", "B1", "B2")]


def test_good_synthesis_homes_demand_with_redundancy() -> None:
    report = validate_synthesis(GOOD_SITES, GOOD)
    assert report["access_sites_with_required_backbone_links"] is True


def test_good_synthesis_has_no_missing_redundancy() -> None:
    assert not demand_without_backbone_redundancy(GOOD, 2)


def test_backbone_mesh_survives_any_one_link_loss_with_fewer_than_two_nodes() -> None:
    synthesis = build_synthesis(("B1",), (), [], [])
    report = validate_synthesis([make_pop("B1")], synthesis)
    assert report["backbone_mesh_survives_any_one_link_loss"] is True


TRIPLE_HOMED = build_synthesis(
    backbone_ids=("B1", "B2", "B3"),
    transit_ids=(),
    access_paths=[AccessPath("s", target, 1.0) for target in ("B1", "B2", "B3")],
    physical_pairs=[("B1", "B2")],
)
TRIPLE_HOMED_SITES = [make_pop(name) for name in ("s", "B1", "B2", "B3")]


def test_homing_passes_at_the_configured_count() -> None:
    report = validate_synthesis(TRIPLE_HOMED_SITES, TRIPLE_HOMED, access_backbone_links=3)
    assert report["access_sites_with_required_backbone_links"] is True


def test_homing_fails_above_the_configured_count() -> None:
    assert demand_without_backbone_redundancy(TRIPLE_HOMED, 2) == ["s"]


def test_homing_fails_below_the_configured_count() -> None:
    report = validate_synthesis(SINGLE_SITES, SINGLE_HOMED)
    assert report["access_sites_with_required_backbone_links"] is False


def test_missing_redundancy_names_the_failing_demand_site() -> None:
    assert demand_without_backbone_redundancy(SINGLE_HOMED, 2) == ["A"]


def _mesh_synthesis(backbone_ids: tuple[str, ...], pairs: list[tuple[str, str]]) -> Synthesis:
    return Synthesis(
        backbone_ids=backbone_ids,
        transit_ids=(),
        access_paths=[],
        fiber_segment_keys={link_key(left, right) for left, right in pairs},
        path_uses=[
            SynthesisPath("backbone_mesh", left, right, (left, right), 1.0) for left, right in pairs
        ],
        metrics=SynthesisMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
    )


def _mesh_report(
    backbone_ids: tuple[str, ...],
    pairs: list[tuple[str, str]],
    backbone_number_of_diverse_paths: int = 3,
    degree_exempt: frozenset[str] = frozenset(),
    ceilings: dict[str, int] | None = None,
) -> ValidationReport:
    return validate_synthesis(
        [make_pop(name) for name in backbone_ids],
        _mesh_synthesis(backbone_ids, pairs),
        targets=MeshRequirements(backbone_number_of_diverse_paths, degree_exempt, ceilings),
    )


_HEALTHY = (
    ("C1", "C2", "C3", "C4", "C5"),
    [("C1", "C2"), ("C2", "C3"), ("C3", "C4"), ("C4", "C5"), ("C5", "C1"),
     ("C1", "C3"), ("C2", "C4"), ("C3", "C5")],
)
_DEFICIENT = (
    ("C1", "C2", "C3", "C4", "C5"),
    [("C1", "C2"), ("C1", "C3"), ("C1", "C4"), ("C2", "C4"), ("C2", "C5"), ("C3", "C5")],
)
_SMALL = (("C1", "C2", "C3"), [("C1", "C2"), ("C2", "C3"), ("C1", "C3")])


def test_backbone_meeting_the_target_satisfies_the_mesh_rule() -> None:
    assert _mesh_report(*_HEALTHY)["backbone_meets_mesh_link_target"] is True


def test_backbone_below_the_target_fails_the_mesh_rule() -> None:
    assert _mesh_report(*_DEFICIENT)["backbone_meets_mesh_link_target"] is False


def test_number_of_diverse_paths_is_configurable() -> None:
    assert _mesh_report(*_DEFICIENT, backbone_number_of_diverse_paths=2)[
        "backbone_meets_mesh_link_target"
    ] is True


def test_backbone_below_the_target_names_the_deficient_nodes() -> None:
    report = _mesh_report(*_DEFICIENT)
    assert {item["id"] for item in report["backbone_diverse_paths_deficient"]} == {"C3", "C4", "C5"}


def test_exempting_every_short_node_satisfies_the_mesh_rule() -> None:
    report = _mesh_report(*_DEFICIENT, degree_exempt=frozenset({"C3", "C4", "C5"}))
    assert report["backbone_meets_mesh_link_target"] is True


def test_exempting_one_short_node_leaves_the_others_reported() -> None:
    report = _mesh_report(*_DEFICIENT, degree_exempt=frozenset({"C3"}))
    assert {item["id"] for item in report["backbone_diverse_paths_deficient"]} == {"C4", "C5"}


def test_the_report_names_the_exempt_nodes() -> None:
    report = _mesh_report(*_DEFICIENT, degree_exempt=frozenset({"C3"}))
    assert report["backbone_degree_exempt"] == [{"id": "C3", "name": "C3"}]


def test_the_report_names_no_exempt_node_by_default() -> None:
    assert _mesh_report(*_HEALTHY)["backbone_degree_exempt"] == []


def test_the_report_names_a_node_whose_target_the_tool_lowered() -> None:
    report = _mesh_report(*_DEFICIENT, ceilings={"C3": 2})
    assert report["backbone_diverse_paths_ceiling_limited"] == [
        {"id": "C3", "name": "C3", "ceiling": 2}
    ]


def test_the_report_lowers_nobody_when_the_fiber_meets_the_degree() -> None:
    assert _mesh_report(*_HEALTHY)["backbone_diverse_paths_ceiling_limited"] == []


def test_the_report_gives_every_measured_node_its_count_and_its_target() -> None:
    report = _mesh_report(*_DEFICIENT, ceilings={"C3": 2, "C4": 4})
    assert report["backbone_diverse_paths_ceilings"] == [
        {"id": "C3", "name": "C3", "ceiling": 2, "target": 2},
        {"id": "C4", "name": "C4", "ceiling": 4, "target": 3},
    ]


def test_the_report_measures_no_node_the_merged_carriers_said_nothing_about() -> None:
    report = _mesh_report(*_DEFICIENT, ceilings={"C3": 2})
    assert [entry["id"] for entry in report["backbone_diverse_paths_ceilings"]] == ["C3"]


def test_small_backbone_is_exempt_from_the_mesh_rule() -> None:
    assert _mesh_report(*_SMALL)["backbone_meets_mesh_link_target"] is True


def _independence_report(paths: list[tuple[str, ...]]) -> ValidationReport:
    return validate_synthesis(
        [make_pop(name) for name in (*fixtures.SHARED_TRANSIT_BACKBONE, "x", "y")],
        fixtures.meshed_backbone_synthesis(paths, fixtures.SHARED_TRANSIT_BACKBONE),
        targets=MeshRequirements(2),
    )


def test_shared_transit_fails_the_independent_mesh_target() -> None:
    assert _independence_report(fixtures.SHARED_TRANSIT_PATHS)[
        "backbone_meets_independent_mesh_link_target"
    ] is False


def test_shared_transit_names_the_node_that_falls_short() -> None:
    report = _independence_report(fixtures.SHARED_TRANSIT_PATHS)
    assert {item["id"] for item in report["backbone_mesh_independence_deficient"]} == {"a"}


def test_diverse_transit_meets_the_independent_mesh_target() -> None:
    assert _independence_report(fixtures.DIVERSE_TRANSIT_PATHS)[
        "backbone_meets_independent_mesh_link_target"
    ] is True


def test_healthy_backbone_survives_any_one_link_loss() -> None:
    assert _mesh_report(*_HEALTHY)["backbone_mesh_survives_any_one_link_loss"] is True


def test_bridged_backbone_is_not_survives_any_one_link_loss() -> None:
    chain = _mesh_synthesis(("C1", "C2", "C3"), [("C1", "C2"), ("C2", "C3")])
    report = validate_synthesis([make_pop(n) for n in ("C1", "C2", "C3")], chain)
    assert report["backbone_mesh_survives_any_one_link_loss"] is False


def _drawn_synthesis(backbone_ids: tuple[str, ...], path_uses: list[SynthesisPath]) -> Synthesis:
    return Synthesis(
        backbone_ids=backbone_ids,
        transit_ids=(),
        access_paths=[],
        fiber_segment_keys=set(),
        path_uses=path_uses,
        metrics=SynthesisMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
    )


_SHARED_CORRIDOR = _drawn_synthesis(
    ("A", "B", "C"),
    [
        SynthesisPath("backbone_mesh", "A", "B", ("A", "X", "B"), 2.0),
        SynthesisPath("backbone_mesh", "A", "C", ("A", "X", "C"), 2.0),
        SynthesisPath("backbone_mesh", "B", "C", ("B", "C"), 1.0),
        SynthesisPath("access", "B", "C", ("B", "C"), 1.0),
    ],
)
_DISJOINT_PATHS = _drawn_synthesis(
    ("A", "B"),
    [
        SynthesisPath("backbone_mesh", "A", "B", ("A", "B"), 1.0),
        SynthesisPath("backbone_mesh", "A", "B", ("A", "Y", "B"), 2.0),
    ],
)


def test_shared_physical_corridor_is_not_survives_any_one_link_loss() -> None:
    report = validate_synthesis([make_pop(n) for n in ("A", "X", "B", "C")], _SHARED_CORRIDOR)
    assert report["backbone_mesh_survives_any_one_link_loss"] is False


def test_segment_disjoint_paths_are_survives_any_one_link_loss() -> None:
    report = validate_synthesis([make_pop(n) for n in ("A", "B", "Y")], _DISJOINT_PATHS)
    assert report["backbone_mesh_survives_any_one_link_loss"] is True


def test_backbone_mesh_survives_any_one_site_loss_with_fewer_than_two_nodes() -> None:
    synthesis = build_synthesis(("B1",), (), [], [])
    report = validate_synthesis([make_pop("B1")], synthesis)
    assert report["backbone_mesh_survives_any_one_site_loss"] is True


def test_healthy_backbone_survives_any_one_site_loss() -> None:
    assert _mesh_report(*_HEALTHY)["backbone_mesh_survives_any_one_site_loss"] is True


def test_chain_backbone_is_not_survives_any_one_site_loss() -> None:
    chain = _mesh_synthesis(("C1", "C2", "C3"), [("C1", "C2"), ("C2", "C3")])
    report = validate_synthesis([make_pop(n) for n in ("C1", "C2", "C3")], chain)
    assert report["backbone_mesh_survives_any_one_site_loss"] is False


def test_an_undrawn_backbone_node_is_not_survives_any_one_site_loss() -> None:
    synthesis = _mesh_synthesis(("C1", "C2", "C3"), [("C1", "C2")])
    report = validate_synthesis([make_pop(n) for n in ("C1", "C2", "C3")], synthesis)
    assert report["backbone_mesh_survives_any_one_site_loss"] is False


_BOWTIE_SYNTHESIS = _drawn_synthesis(
    ("B1", "B2", "B3", "B4"),
    [
        SynthesisPath("backbone_mesh", "B1", "B2", ("B1", "B2"), 1.0),
        SynthesisPath("backbone_mesh", "B2", "H", ("B2", "H"), 1.0),
        SynthesisPath("backbone_mesh", "B1", "H", ("B1", "H"), 1.0),
        SynthesisPath("backbone_mesh", "H", "B3", ("H", "B3"), 1.0),
        SynthesisPath("backbone_mesh", "B3", "B4", ("B3", "B4"), 1.0),
        SynthesisPath("backbone_mesh", "H", "B4", ("H", "B4"), 1.0),
    ],
)
_BOWTIE_SITES = [make_pop(name) for name in ("B1", "B2", "B3", "B4", "H")]


def test_bowtie_backbone_survives_any_one_link_loss() -> None:
    report = validate_synthesis(_BOWTIE_SITES, _BOWTIE_SYNTHESIS)
    assert report["backbone_mesh_survives_any_one_link_loss"] is True


def test_bowtie_backbone_is_not_survives_any_one_site_loss() -> None:
    report = validate_synthesis(_BOWTIE_SITES, _BOWTIE_SYNTHESIS)
    assert report["backbone_mesh_survives_any_one_site_loss"] is False


_DISCONNECTED = build_synthesis(
    backbone_ids=("B1", "B2", "B3", "B4"),
    transit_ids=(),
    access_paths=[],
    physical_pairs=[("B1", "B2"), ("B3", "B4")],
)
_DISCONNECTED_SITES = [make_pop(name) for name in ("B1", "B2", "B3", "B4")]


def test_disconnected_synthesis_reports_multiple_components() -> None:
    report = validate_synthesis(_DISCONNECTED_SITES, _DISCONNECTED)
    assert report["component_count"] == 2


def test_disconnected_synthesis_skips_articulation_search() -> None:
    report = validate_synthesis(_DISCONNECTED_SITES, _DISCONNECTED)
    assert report["articulation_points"] == []


def test_degree_deficient_site_is_named() -> None:
    report = validate_synthesis(_DISCONNECTED_SITES, _DISCONNECTED)
    assert {item["id"] for item in report["degree_deficient_sites"]} == {
        "B1", "B2", "B3", "B4",
    }


def test_empty_synthesis_reports_zero_min_degree() -> None:
    empty = build_synthesis((), (), [], [])
    assert validate_synthesis([], empty)["min_distinct_neighbor_degree"] == 0


def test_articulation_point_is_flagged() -> None:
    chain = _mesh_synthesis(("C1", "C2", "C3"), [("C1", "C2"), ("C2", "C3")])
    report = validate_synthesis([make_pop(n) for n in ("C1", "C2", "C3")], chain)
    assert {item["id"] for item in report["articulation_points"]} == {"C2"}
