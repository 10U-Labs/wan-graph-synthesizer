"""Unit tests for reporting a backbone site that holds more links than it asked for.

The number of diverse paths is the number a site gets, so a site above it is the exception
and every link taking it there is somebody else's requirement rather than the tool being
generous with an operator's cable. There are exactly four such requirements, and the report
has to name which one, because a count on its own leaves a reader to guess why the network
they were handed is bigger than the one they ordered.

Each test below hands site ``a`` the two links it asked for plus one more, varying only
what put that third link there.
"""

from __future__ import annotations

import pytest

import fixtures
from synthesizer.model import (
    LINK_FOR_CITY_DETOUR,
    LINK_FOR_CONNECTIVITY,
    LINK_FOR_PIN,
    LINK_FOR_TARGET,
    Design,
    DesignMetrics,
    MeshTargets,
    PathUse,
)
from synthesizer.validation import validate_design

_SITES = ("a", "b", "c", "d")
_TARGET = 2


def _link(peer: str, reason: str, requested_by: tuple[str, ...] = ()) -> PathUse:
    """One routed mesh link from ``a`` to ``peer``, carrying why it is there."""
    return PathUse("backbone_mesh", "a", peer, ("a", peer), 1.0, reason, requested_by)


# The two links site a reached for itself, which are the two its tenant asked for.
_ASKED_FOR = [
    _link("b", LINK_FOR_TARGET, ("a",)),
    _link("c", LINK_FOR_TARGET, ("a",)),
]


def _above_target(*extra: PathUse) -> list[dict[str, object]]:
    """The above-target rows for a design giving site a its two links plus ``extra``."""
    design = Design(
        backbone_ids=_SITES,
        transit_ids=(),
        access_edges=[],
        physical_edge_keys=set(),
        path_uses=[*_ASKED_FOR, *extra],
        metrics=DesignMetrics(score=0.0, access_miles=0.0, physical_miles=0.0),
    )
    report = validate_design(
        [fixtures.carrier_pop(site) for site in _SITES],
        design,
        targets=MeshTargets(_TARGET),
    )
    return report["backbone_diverse_paths_above_target"]


def test_a_site_holding_exactly_what_it_asked_for_is_not_reported() -> None:
    """Two links against a target of two is the design working, not a thing to report."""
    assert _above_target() == []


@pytest.mark.parametrize(
    ("reason", "requested_by", "reported"),
    [
        (LINK_FOR_PIN, (), "operator_pin"),
        (LINK_FOR_TARGET, ("d",), "peer_target"),
        (LINK_FOR_CONNECTIVITY, (), "network_connectivity"),
        (LINK_FOR_CITY_DETOUR, (), "city_detour"),
    ],
)
def test_a_link_past_the_target_names_the_requirement_that_put_it_there(
    reason: str, requested_by: tuple[str, ...], reported: str
) -> None:
    """Each of the four grounds for exceeding a target is reported as that ground.

    An operator pinned it; a peer needed this site to reach its own target and a link has
    two ends; it holds the backbone together as one network; or it is a detour keeping one
    city off the only path. A link on none of these grounds is not built at all, which is
    what makes naming the ground worth doing.
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
    assert [item["peer"] for item in rows[0]["unrequested_links"]] == ["d"]
