"""Layer 4 (delivered designs): the published networks answer the targets their configs set.

Layers 1 to 3 stop at the shape of the deployment. The synthesizer exists, its runtime and
memory match the declaration, and its role can reach the store -- and none of that reads a
design. A synthesizer that publishes a network missing its coverage target by more than a
factor of two passes every one of those assertions, because the build was accepted and the
status said ``ready``, which is exactly how GitHub issue #41 stayed invisible from outside
while DAF sat at 518 miles against a 200-mile target. This layer reads what was published
and measures it.

The measurement here does not go through ``synthesizer.coverage``. The report under test is
what that module produced, so recomputing with it would only establish that it agrees with
itself. Only ``haversine_miles`` is borrowed, since the distance between two points on the
globe is not the thing in question.

The last test is the one that would have failed on the old DAF build. A design that ends
below its target has either spent every backbone seat its operator allowed or given up
early, and only the second is a defect. Minuteman was the first kind: it pins six cities
into a backbone capped at six, so the coverage pass had nothing left to seat and missed a
400-mile target by 484 miles, which is the honest answer to a question its own config had
already settled (GitHub issue #42, closed by moving the target to what those six cities
deliver). DAF, at 34 seats against a cap of 99, had no such excuse.
"""
from __future__ import annotations

from typing import Any

from synthesizer.input_graph import Vertex, haversine_miles


def _vertex(node: dict[str, Any]) -> Vertex:
    """Rebuild a published node as the vertex type the distance helper takes."""
    latitude, longitude = node["coords"]
    return Vertex(node["id"], node["name"], node["kind"], (latitude, longitude))


def _worst_haul(design: dict[str, Any]) -> float:
    """The farthest any site the target applies to sits from its nearest backbone node.

    Sites the operator has excused the distance constraint are left out, as they are in the
    synthesizer's own stop condition, and a design carrying no demand at all reads zero.
    """
    nodes = [_vertex(node) for node in design["backbone"]]
    hauls = [
        min(haversine_miles(_vertex(site), node) for node in nodes)
        for site in design["demand"]
        if not site["exempt_from_distance_constraint"]
    ]
    return round(max(hauls, default=0.0), 1)


def test_every_tenant_the_roster_declares_has_a_published_network(
        delivered_designs: list[dict[str, Any]]) -> None:
    """No tenant git declares is left without a WAN the synthesizer finished building."""
    unfinished = {
        design["tenant"]: design["status"].get("status")
        for design in delivered_designs
        if design["status"].get("status") != "ready"
    }
    assert unfinished == {}


def test_every_published_network_reports_the_coverage_it_delivered(
        delivered_designs: list[dict[str, Any]]) -> None:
    """A published status says what the design did about its target, not only ``ready``.

    That one word was all a reader outside the synthesizer used to get, and it read the same
    whether the coverage pass met the target or ran out of things to try.
    """
    silent = [
        design["tenant"] for design in delivered_designs if "coverage" not in design["status"]
    ]
    assert silent == []


def test_every_report_is_measured_against_the_target_its_tenant_declares(
        delivered_designs: list[dict[str, Any]]) -> None:
    """Each published network has caught up with the target its tenant's config sets.

    The number travels from ``etc/`` through seed, the knobs resource and the tuning block
    before it reaches the report, and a report judged against some other number would look
    perfectly well formed at the end of that journey. Because a config change is delivered
    by a workflow independent of this one, the fixture gives the store until its deadline
    to converge, so what fails here is a target that never reached the network at all --
    a tenant seed stopped short of, or a build that failed and was left where it fell.
    """
    reported = {
        design["tenant"]: design["status"]["coverage"]["target_miles"]
        for design in delivered_designs
    }
    declared = {design["tenant"]: design["target_miles"] for design in delivered_designs}
    assert reported == declared


def test_the_reported_worst_haul_is_the_one_the_published_network_delivers(
        delivered_designs: list[dict[str, Any]]) -> None:
    """The worst haul a status claims is the worst haul its own published network has.

    Measured off the backbone and the sites as published, so the claim is checked against
    the artifact an operator reads rather than against the run that wrote it.
    """
    mismeasured = [
        (design["tenant"], _worst_haul(design))
        for design in delivered_designs
        if _worst_haul(design) != design["status"]["coverage"]["worst_haul_miles"]
    ]
    assert mismeasured == []


def test_no_design_stopped_short_of_its_target_with_a_seat_left_to_spend(
        delivered_designs: list[dict[str, Any]]) -> None:
    """A design that ended below its coverage target had spent every seat it was allowed.

    This is the assertion the defect had to get past. Growth that halts with seats still
    free has decided no remaining candidate is worth taking, and on the old DAF build that
    decision was wrong twice over: sixteen seats used of ninety-nine, and every site the
    target applied to more than twice as far out as the target allowed.
    """
    gave_up_early = [
        (design["tenant"], len(design["backbone"]), design["seat_cap"])
        for design in delivered_designs
        if not design["status"]["coverage"]["met"]
        and len(design["backbone"]) < design["seat_cap"]
    ]
    assert gave_up_early == []


# How far a fiber route wanders past the straight line between its two ends. Route miles
# run somewhere between one and two air miles on real terrestrial builds, so a published
# link measured against the great-circle distance is allowed twice its tenant's bound.
_SINUOSITY = 2.0


def _overrun_links(design: dict[str, Any]) -> list[tuple[str, float]]:
    """Every published backbone link routed further than even a generous bound allows."""
    coords = {node["id"]: _vertex(node) for node in design["backbone"]}
    allowed = _SINUOSITY * design["max_path_stretch"]
    overrun = []
    for link in design["links"]:
        source = coords.get(link["source_id"])
        target = coords.get(link["target_id"])
        if source is None or target is None or source is target:
            continue
        direct = haversine_miles(source, target)
        if direct > 0 and link["distance_miles"] > allowed * direct:
            overrun.append((" -> ".join(link["path"]), link["distance_miles"] / direct))
    return overrun


def test_no_published_link_is_routed_further_than_its_tenant_allows(
        delivered_designs: list[dict[str, Any]]) -> None:
    """No backbone link wanders far past the direct distance between the two sites it joins.

    This is the assertion GitHub issue #44 had to get past. DAF's published network
    protected Ashburn to New York, 220 miles apart, along a 7,471-mile path through Paris,
    and protected Seattle to Hillsboro through Tokyo at 9,607 miles against 161 -- because
    the proof behind the mesh counted routes that share no city and read no distance at all.

    Measured against the great-circle distance rather than the shortest fiber route, since
    the published collections carry no substrate to route over and rebuilding one here would
    reimplement the router this layer exists to check from the outside. Great-circle is the
    shorter denominator, so the ratio it yields overstates the real stretch and the bound is
    loosened by ``_SINUOSITY`` to stay sound. That leaves it far looser than what the
    synthesizer enforces -- six times the direct distance rather than three -- and it still
    catches every route the defect produced, the nearest of which ran twelve times.
    """
    overrun = {
        design["tenant"]: _overrun_links(design)
        for design in delivered_designs
        if _overrun_links(design)
    }
    assert overrun == {}
