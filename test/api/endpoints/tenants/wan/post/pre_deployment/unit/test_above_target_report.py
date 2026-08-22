from __future__ import annotations

from typing import cast

import pytest

import fixtures
from synthesizer.model import (
    LINK_FOR_PIN,
    LINK_FOR_TARGET,
    Synthesis,
    SynthesisMetrics,
    MeshRequirements,
    SynthesisPath,
)
from synthesizer.validation import validate_synthesis

_SITES = ("a", "b", "c", "d")
_TARGET = 2


def _link(peer: str, reason: str, requested_by: tuple[str, ...] = ()) -> SynthesisPath:
    return SynthesisPath("backbone_mesh", "a", peer, ("a", peer), 1.0, reason, requested_by)


_ASKED_FOR = [
    _link("b", LINK_FOR_TARGET, ("a",)),
    _link("c", LINK_FOR_TARGET, ("a",)),
]


def _above_target(*extra: SynthesisPath) -> list[dict[str, object]]:
    synthesis = Synthesis(
        backbone_ids=_SITES,
        transit_ids=(),
        access_paths=[],
        fiber_segment_keys=set(),
        path_uses=[*_ASKED_FOR, *extra],
        metrics=SynthesisMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
    )
    report = validate_synthesis(
        [fixtures.carrier_pop(site) for site in _SITES],
        synthesis,
        targets=MeshRequirements(_TARGET),
    )
    return report["backbone_diverse_paths_above_target"]


def test_a_site_holding_exactly_what_it_asked_for_is_not_reported() -> None:
    assert not _above_target()


@pytest.mark.parametrize(
    ("reason", "requested_by", "reported"),
    [
        (LINK_FOR_PIN, (), "operator_pin"),
        (LINK_FOR_TARGET, ("d",), "peer_target"),
    ],
)
def test_a_link_past_the_target_names_the_requirement_that_put_it_there(
    reason: str, requested_by: tuple[str, ...], reported: str
) -> None:
    rows = _above_target(_link("d", reason, requested_by))
    assert rows[0]["unrequested_links"] == [{"peer": "d", "reason": reported}]


def test_the_report_names_the_site_that_went_over() -> None:
    rows = _above_target(_link("d", LINK_FOR_PIN))
    assert [row["id"] for row in rows] == ["a"]


def test_the_report_shows_the_arithmetic_it_is_claiming() -> None:
    rows = _above_target(_link("d", LINK_FOR_PIN))
    assert (rows[0]["target"], rows[0]["link_count"]) == (_TARGET, 3)


def test_a_sites_own_links_are_not_reported_as_unrequested() -> None:
    rows = _above_target(_link("d", LINK_FOR_PIN))
    links = cast(list[dict[str, object]], rows[0]["unrequested_links"])
    assert [item["peer"] for item in links] == ["d"]
