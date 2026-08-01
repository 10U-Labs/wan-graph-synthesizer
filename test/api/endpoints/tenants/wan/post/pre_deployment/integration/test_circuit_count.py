"""Integration test: how many circuits a synthesis builds when the fiber is generous.

Every other fixture in this tier is as tight as the request -- a six-point ring gives each
point two fiber directions and the tenant asks for two -- so the choice between taking what
was asked for and taking everything the ground offers is a choice none of them can show.
This graph is a six-site clique: each site's fiber reaches all five others directly, so a
design that treats the tenant's number as a floor wires the full mesh of fifteen circuits.

Distances rise with the gap between site numbers, so each site's nearest peers are its
neighbours rather than one hub, which is what makes the finished design a real topology and
not a star. The tenant asks for two diverse paths.
"""

from __future__ import annotations

from itertools import combinations
from typing import cast

import fixtures
from fixtures import run_design
from synthesizer.model import DesignParams, Tuning
from synthesizer.validation import backbone_mesh_pairs

_SITES = tuple(f"S{index}" for index in range(6))
_ASKED_FOR = 2
# A clique: every pair has its own span, priced by how far apart the two sites sit.
_SPANS = {
    (_SITES[left], _SITES[right]): 100.0 * (right - left)
    for left, right in combinations(range(len(_SITES)), 2)
}
ARTIFACTS = run_design(
    [
        fixtures.carrier_pop(site, 38.0, -115.0 + 2.0 * index)
        for index, site in enumerate(_SITES)
    ],
    fixtures.physical_edges_from(_SPANS),
    DesignParams(
        min_backbone_count=2,
        forced_backbone_names=_SITES,
        datacenter_cities=frozenset((site, "XX") for site in _SITES),
        promote_high_degree_convergences=False,
        tuning=Tuning(backbone_number_of_diverse_paths=_ASKED_FOR),
    ),
)


def test_the_design_does_not_wire_the_full_mesh() -> None:
    """Nine circuits where the fiber would have allowed fifteen.

    The six circuits not built are the ones no site asked for and no other requirement
    needed. Under the old behaviour each site was aimed at what its fiber could carry, so
    all fifteen were built and a tenant asking for two got a full mesh.
    """
    assert len(backbone_mesh_pairs(ARTIFACTS.design)) == 9


def test_the_site_nobody_reached_for_holds_exactly_what_it_asked_for() -> None:
    """S5 sits at the far end, so no peer picks it and its own two picks are its whole wiring."""
    links = [
        use
        for use in ARTIFACTS.design.path_uses
        if use.purpose == "backbone_mesh" and "S5" in (use.source, use.target)
    ]
    assert len(links) == _ASKED_FOR


def test_every_circuit_past_the_number_names_the_requirement_behind_it() -> None:
    """No site is over on the tool's own account; each extra circuit traces to a reason.

    Three of the four grounds appear on this one graph: a peer reaching for its own number,
    a link holding the backbone together as one network, and a detour keeping a city off
    the only path. A link on none of the grounds would be one the tool bought because the
    ground was generous, which is the thing being removed.
    """
    above = ARTIFACTS.validation["backbone_diverse_paths_above_target"]
    assert {
        str(link["reason"])
        for entry in above
        for link in cast(list[dict[str, object]], entry["unrequested_links"])
    } == {"peer_target", "network_connectivity", "city_detour"}


def test_no_site_is_reported_above_the_number_with_nothing_to_blame() -> None:
    """A site over the number always has at least one link it did not reach for."""
    above = ARTIFACTS.validation["backbone_diverse_paths_above_target"]
    assert all(entry["unrequested_links"] for entry in above)
