"""Unit tests for reporting a backbone site that holds more links than it asked for.

The number of diverse paths is the number a site gets, so a site above it is the exception
and every link taking it there is somebody else's requirement rather than the tool being
generous with an operator's fiber. There are exactly two such requirements, and the report
has to name which one, because a count on its own leaves a reader to guess why the network
they were handed is bigger than the one they ordered.

There were five until GitHub issue #60. Three of them named a pass that added a link after
the fact -- a join holding the backbone together, a detour around a city carrying the whole
network, a second path to a peer already reached -- and those passes are gone, the fiber
being chosen for the whole synthesis at once now. What is left is a peer that reached for this
site, and the operator's own pin.

Each test below hands site ``a`` the two links it asked for plus one more, varying only
what put that third link there.
"""

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
    """One drawn mesh link from ``a`` to ``peer``, carrying why it is there."""
    return SynthesisPath("backbone_mesh", "a", peer, ("a", peer), 1.0, reason, requested_by)


# The two links site a reached for itself, which are the two its tenant asked for.
_ASKED_FOR = [
    _link("b", LINK_FOR_TARGET, ("a",)),
    _link("c", LINK_FOR_TARGET, ("a",)),
]


def _above_target(*extra: SynthesisPath) -> list[dict[str, object]]:
    """The above-target rows for a synthesis giving site a its two links plus ``extra``."""
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
    """Two links against a target of two is the synthesis working, not a thing to report."""
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
    """Each of the two grounds for exceeding a target is reported as that ground.

    An operator pinned it, or a peer needed this site to reach its own target and a link
    has two ends. A link on neither ground is not built at all, which is what makes naming
    the ground worth doing.
    """
    rows = _above_target(_link("d", reason, requested_by))
    assert rows[0]["unrequested_links"] == [{"peer": "d", "reason": reported}]


def test_the_report_names_the_site_that_went_over() -> None:
    """The row is site a's, since b, c and d each hold one link and owe two."""
    rows = _above_target(_link("d", LINK_FOR_PIN))
    assert [row["id"] for row in rows] == ["a"]


def test_the_report_shows_the_arithmetic_it_is_claiming() -> None:
    """Target beside link count, so a reader is not left deriving the surplus."""
    rows = _above_target(_link("d", LINK_FOR_PIN))
    assert (rows[0]["target"], rows[0]["link_count"]) == (_TARGET, 3)


def test_a_sites_own_links_are_not_reported_as_unrequested() -> None:
    """The two links a asked for are its own, however many other links it ends up with."""
    rows = _above_target(_link("d", LINK_FOR_PIN))
    links = cast(list[dict[str, object]], rows[0]["unrequested_links"])
    assert [item["peer"] for item in links] == ["d"]
