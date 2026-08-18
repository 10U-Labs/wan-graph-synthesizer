"""Integration test: how many paths a synthesis builds when the fiber is generous.

Every other fixture in this tier is as tight as the request -- a six-point ring gives each
point two fiber directions and the tenant asks for two -- so the choice between taking what
was asked for and taking everything the ground offers is a choice none of them can show.
This graph is a six-site clique: each site's fiber reaches all five others directly, so a
design that treats the tenant's number as a floor wires the full mesh of fifteen paths.

Distances rise with the gap between site numbers, so each site's nearest peers are its
neighbours rather than one hub, which is what makes the finished design a real topology and
not a star. The tenant asks for two diverse paths.

What this file asks changed with GitHub issue #60. It used to pin the exact number of pairs
the four passes happened to join, and the four passes are gone: the fiber for the whole
design is chosen at once now, so which pairs end up joined falls out of that choice and a
number written down here would pin an answer nobody argued for. What is worth pinning is
what the tenant bought -- that a generous graph does not become a full mesh, that every
path in the design answers somebody's requirement, and that no path in it could be taken
back out without costing somebody something.
"""

from __future__ import annotations

from itertools import combinations
from typing import cast

import fixtures
from fixtures import run_design
from synthesizer.backbone import _needed
from synthesizer.model import LINK_FOR_TARGET, DesignParams, Tuning
from synthesizer.validation import backbone_mesh_pairs

_SITES = tuple(f"S{index}" for index in range(6))
_ASKED_FOR = 2
_FULL_MESH = len(_SITES) * (len(_SITES) - 1) // 2
# A clique: every pair has its own fiber segment, priced by how far apart the two sites sit.
_SEGMENTS = {
    (_SITES[left], _SITES[right]): 100.0 * (right - left)
    for left, right in combinations(range(len(_SITES)), 2)
}
ARTIFACTS = run_design(
    [
        fixtures.carrier_pop(site, 38.0, -115.0 + 2.0 * index)
        for index, site in enumerate(_SITES)
    ],
    fixtures.physical_edges_from(_SEGMENTS),
    DesignParams(
        min_backbone_count=2,
        forced_backbone_names=_SITES,
        datacenter_cities=frozenset((site, "XX") for site in _SITES),
        promote_high_degree_convergences=False,
        tuning=Tuning(backbone_number_of_diverse_paths=_ASKED_FOR),
    ),
)
_MESH = [use for use in ARTIFACTS.design.path_uses if use.purpose == "backbone_mesh"]


def test_the_design_does_not_wire_the_full_mesh() -> None:
    """Fewer pairs joined than the fiber would have allowed, on a graph that allows all of them.

    Under the behaviour before the ceiling was computed, each site was aimed at what its
    fiber could carry, so all fifteen pairs were built and a tenant asking for two diverse
    paths was handed a full mesh.
    """
    assert len(backbone_mesh_pairs(ARTIFACTS.design)) < _FULL_MESH


def test_every_site_still_holds_the_paths_its_tenant_asked_for() -> None:
    """Buying less fiber is only worth doing if it costs no site a way out, so nobody is short."""
    assert ARTIFACTS.validation["backbone_mesh_independence_deficient"] == []


def test_every_path_in_the_design_answers_a_sites_own_requirement() -> None:
    """No path is here because the ground was generous; each one is a site's own way out.

    The operator pinned nothing on this graph, so the only ground left is a site reaching
    for the number of diverse paths it was bought. A path on no ground at all is exactly
    what GitHub issue #60 found 54 of.
    """
    assert {use.reason for use in _MESH} == {LINK_FOR_TARGET}


def test_no_path_in_the_design_could_be_taken_back_out() -> None:
    """Removing any one path costs a site a way out, breaks the backbone, or exposes a city.

    This is the property the whole of GitHub issue #60 is about, asked of a design the
    pipeline built end to end rather than of a fiber choice on its own. A generous graph is
    where it matters: there is always another defensible path to add, and the old passes
    added 54 of them across the six published networks.
    """
    assert _needed(_MESH, ARTIFACTS.design.backbone_ids, _ASKED_FOR) == _MESH


def test_no_site_is_reported_above_the_number_with_nothing_to_blame() -> None:
    """A site over the number always has at least one path it did not reach for."""
    above = ARTIFACTS.validation["backbone_diverse_paths_above_target"]
    assert all(entry["unrequested_links"] for entry in above)


def test_every_path_past_the_number_names_the_peer_that_reached_for_it() -> None:
    """A site holding more than it asked for is holding a peer's path, and the report says so.

    Three grounds used to appear on this one graph: a peer reaching for its own number, a
    path holding the backbone together as one network, and a detour keeping a city off the
    only path. The last two were passes that added a path after the fact, and the fiber is
    chosen for the whole design at once now, so a peer's own requirement is the only ground
    left that a graph with no operator pins on it can produce.
    """
    above = ARTIFACTS.validation["backbone_diverse_paths_above_target"]
    assert {
        str(link["reason"])
        for entry in above
        for link in cast(list[dict[str, object]], entry["unrequested_links"])
    } <= {"peer_target"}
