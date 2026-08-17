"""Whether the tenant configs in etc/ synthesize into the networks they ask for.

``scripts/seed.py`` PUTs every ``etc/*.yml`` to the API and then POSTs one build per
tenant. This is that journey read back the way a caller reads it: each tenant's published
status and its backbone, demand and links collections, measured against the
``target_miles``, ``max_backup_route_multiple``, ``seat_cap`` and pinned cities its own config sets.
What fails here is as often a config asking for something its other settings rule out as it
is a defect in the synthesizer -- GitHub issue #42 was closed by moving a target in
etc/minuteman.yml, with no code changed at all.

Nothing else asks this. The three files left under
test/api/endpoints/tenants/wan/post/post_deployment/integration/ stop at the shape of the
deployment: the synthesizer exists, its runtime and memory match the declaration, and its
role can reach the store -- and none of that reads a design. A synthesizer that publishes a
network missing its coverage target by more than a factor of two passes every one of those
assertions, because the build was accepted and the status said ``ready``, which is exactly
how GitHub issue #41 stayed invisible from outside while DAF sat at 518 miles against a
200-mile target.

The measurement itself is not here. Four of the ten questions below are answered by
recomputing a number from the published collections rather than by reading one back, and
that recomputation lives in lib/python/test_published_designs/, where a unit tier can hold
it to literal inputs. A helper that measures wrongly fails a healthy network or passes a
broken one depending on which way its error runs, and this tier has no second source of the
answer with which to notice; leaving it here left it graded only by the deployment it
exists to grade (GitHub issue #50). What that module does not do is measure through
``synthesizer.coverage``: the report under test is what that module produced, so
recomputing with it would only establish that it agrees with itself.

``test_no_design_stopped_short_of_its_target_with_a_seat_left_to_spend`` is the one that
would have failed on the old DAF build. A design that ends
below its target has either spent every backbone seat its operator allowed or given up
early, and only the second is a defect. Minuteman was the first kind: it pins six cities
into a backbone capped at six, so the coverage pass had nothing left to seat and missed a
400-mile target by 484 miles, which is the honest answer to a question its own config had
already settled (GitHub issue #42, closed by moving the target to what those six cities
deliver). DAF, at 34 seats against a cap of 99, had no such excuse.
"""
from __future__ import annotations

from typing import Any

from test_published_designs import (
    detoured_links,
    overbuilt_pairs,
    overrun_links,
    worst_haul,
)


def _published_cities(design: dict[str, Any]) -> set[str]:
    """The cities the published backbone seats, by the ``City, ST`` names a config pins by."""
    return {node["name"] for node in design["backbone"]}


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
    perfectly well formed at the end of that journey. The ``seeding`` job that delivers the
    config returns as soon as each build is recorded, not when it finishes, so the fixture
    gives every tenant until its deadline to settle; what fails here is a target that never
    reached the network at all -- a tenant seed stopped short of, or a build that failed
    and was left where it fell.
    """
    reported = {
        design["tenant"]: design["status"]["coverage"]["target_miles"]
        for design in delivered_designs
    }
    declared = {design["tenant"]: design["target_miles"] for design in delivered_designs}
    assert reported == declared


def test_every_city_a_tenant_pins_is_seated_in_its_published_backbone(
        delivered_designs: list[dict[str, Any]]) -> None:
    """Each city named in a tenant's ``backbone.forced.nodes`` is in its backbone tier.

    A pinned city is the one requirement an operator states as a plain fact about the
    finished network: put a backbone node here, whatever the coverage pass would rather do.
    Nothing outside the synthesizer checked that the fact came true, so a config that moved
    a pin and a network still seated on the old one read exactly alike -- which is how a
    change to this setting could pass this whole tier against a network built before it
    (GitHub issue #47).
    """
    unseated = {
        design["tenant"]: sorted(set(design["forced"]) - _published_cities(design))
        for design in delivered_designs
        if not set(design["forced"]) <= _published_cities(design)
    }
    assert unseated == {}


def test_the_reported_worst_haul_is_the_one_the_published_network_delivers(
        delivered_designs: list[dict[str, Any]]) -> None:
    """The worst haul a status claims is the worst haul its own published network has.

    Measured off the backbone and the sites as published, so the claim is checked against
    the artifact an operator reads rather than against the run that wrote it.
    """
    mismeasured = [
        (design["tenant"], worst_haul(design))
        for design in delivered_designs
        if worst_haul(design) != design["status"]["coverage"]["worst_haul_miles"]
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
    shorter denominator, so the ratio it yields overstates the real multiple and the bound is
    loosened by ``SINUOSITY`` to stay sound. That leaves it far looser than what the
    synthesizer enforces -- six times the direct distance rather than three -- and it still
    catches every route the defect produced, the nearest of which ran twelve times.
    """
    overrun = {
        design["tenant"]: overrun_links(design)
        for design in delivered_designs
        if overrun_links(design)
    }
    assert overrun == {}


def test_no_published_link_wanders_past_the_fiber_its_own_network_carries(
        delivered_designs: list[dict[str, Any]]) -> None:
    """No backbone link runs far past the cheapest way over the fiber the design ordered.

    The assertion above measures each link against the straight line between its two sites,
    which is why it has to be loosened to six times the tenant's bound: real fiber does not
    fly. This one measures it against fiber -- the published ``edges`` collection carries
    every carrier span the design routed over, so the shortest way between the two sites is
    recomputable from outside the build and the tenant's own ``max_backup_route_multiple`` can be
    applied to it without slack.

    What it cannot ask is whether the *set* of routes out of a site is the shortest set that
    holds that many independent links, which is what GitHub issue #57 is about: the proof
    behind the mesh chose the routes crossing the fewest cities rather than the ones running
    the least cable, and a set of needlessly long routes can pass here with every link in it
    inside the bound. The routes proved and never drawn are not published at all. This is
    the strongest statement available from outside, and it needs nothing added to what the
    synthesizer publishes.
    """
    wandering = {
        design["tenant"]: detoured_links(design)
        for design in delivered_designs
        if detoured_links(design)
    }
    assert wandering == {}


def test_no_published_network_leaves_a_site_short_of_the_links_it_was_asked_for(
        delivered_designs: list[dict[str, Any]]) -> None:
    """No live tenant reports a site holding fewer independent links than it was asked for.

    A site is asked for the smaller of the tenant's own diverse-path number and the count of
    ways out its fiber proves, and the mesh then lays what it can. A count proved over
    routes the backup route multiple forbids asks for a link the router will not draw, and
    the site is reported short of it for the rest of the build's life -- a shortfall an
    operator reads, investigates and cannot close, because the missing link is one the
    bound itself refuses (GitHub issue #45).

    Read straight out of the status rather than guarded for, because a build that published
    no such finding is itself the failure this asks about: the shortfall appears nowhere in
    the collections, so a status that has stopped reporting it has taken the question away
    rather than answered it.
    """
    short = {
        design["tenant"]: design["status"]["diverse_paths"]["short"]
        for design in delivered_designs
    }
    assert {tenant: sites for tenant, sites in short.items() if sites} == {}


def test_no_published_network_draws_a_pair_more_routes_than_its_tenant_bought(
        delivered_designs: list[dict[str, Any]]) -> None:
    """No two backbone sites are joined by more routes than the tenant's config allows.

    A pair is allowed one route wherever the tenant's seats leave its sites other peers to
    reach, which is five of the six; Two-Node is capped at two seats, so its one pair is
    allowed the two paths it buys (see ``test_published_designs.overbuilt_pairs``). Measured
    against the tenant's number alone, twenty-one pairs across DAF, F-35, AFGSC and
    Minuteman were passing while they carried 17,013 route miles nobody ordered (GitHub
    issue #59).

    The counterpart of the shortfall above, and the half that was missing. Every question
    this layer asked about routes asked it of one route at a time -- is this one inside the
    bound, is this one the shortest way over the fiber -- so a network could hold any number
    of them and answer yes every time. Two-Node did: five routes between Ashburn, VA and
    Salt Lake City, UT, each of them sound on its own, 5,633 miles of haul nobody ordered,
    and not one published measurement with anything to say about it (GitHub issue #58).

    Asked against the number in ``etc/`` rather than the one the build reported, because the
    question is whether the network an operator has is the network their config asks for.
    A build published before they last moved the number is measured against what they want
    now, which is the finding.
    """
    overbuilt = {
        design["tenant"]: overbuilt_pairs(design)
        for design in delivered_designs
        if overbuilt_pairs(design)
    }
    assert overbuilt == {}
