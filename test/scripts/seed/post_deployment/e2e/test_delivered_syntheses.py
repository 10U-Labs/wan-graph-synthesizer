"""Whether the tenant configs in etc/ synthesize into the networks they ask for.

``scripts/seed.py`` PUTs every ``etc/*.yml`` to the API and then POSTs one build per
tenant. This is that journey read back the way a caller reads it: each tenant's published
status and its backbone, demand and links collections, measured against the
``target_miles``, ``max_backup_path_multiple``, ``seat_cap`` and pinned cities its own config sets.
What fails here is as often a config asking for something its other settings rule out as it
is a defect in the synthesizer -- GitHub issue #42 was closed by moving a target in
etc/minuteman.yml, with no code changed at all.

Nothing else asks this. The three files left under
test/api/endpoints/tenants/wan/post/post_deployment/integration/ stop at the shape of the
deployment: the synthesizer exists, its runtime and memory match the declaration, and its
role can reach the store -- and none of that reads a synthesis. A synthesizer that publishes a
network missing its coverage target by more than a factor of two passes every one of those
assertions, because the build was accepted and the status said ``success``, which is
exactly
how GitHub issue #41 stayed invisible from outside while DAF sat at 518 miles against a
200-mile target.

The measurement itself is not here. Ten of the eighteen questions below are answered by
recomputing a number from the published collections, or from the carrier files git holds,
rather than by reading one back, and that recomputation lives in
lib/python/test_published_syntheses/, where a unit tier can hold it to literal inputs. A
helper that measures wrongly fails a healthy network or passes a broken one depending on
which way its error runs, and this tier has no second source of the
answer with which to notice; leaving it here left it graded only by the deployment it
exists to grade (GitHub issue #50). What that module does not do is measure through
``synthesizer.coverage``: the report under test is what that module produced, so
recomputing with it would only establish that it agrees with itself.

``test_no_synthesis_stopped_short_of_its_target_with_a_seat_left_to_spend`` is the one that
would have failed on the old DAF build. A synthesis that ends
below its target has either spent every backbone seat its operator allowed or given up
early, and only the second is a defect. Minuteman was the first kind: it pins six cities
into a backbone capped at six, so the coverage pass had nothing left to seat and missed a
400-mile target by 484 miles, which is the honest answer to a question its own config had
already settled (GitHub issue #42, closed by moving the target to what those six cities
deliver). DAF, at 34 seats against a cap of 99, had no such excuse.
"""
from __future__ import annotations

import csv
from collections.abc import Callable
from typing import Any

import seed
from test_published_syntheses import (
    FIBER,
    backbone_groups,
    cut_cities,
    detoured_links,
    ordered_fiber_miles,
    overbuilt_pairs,
    overrun_links,
    removable_paths,
    sellable_ways_out,
    worst_haul,
)


# The precision every mileage is published at: a thousandth of a mile, about a metre and a
# half.
_ROUNDED_TO = 0.001


def _rounding_slack(synthesis: dict[str, Any]) -> float:
    """How far the two mileages a synthesis is judged by can differ on rounding alone.

    A build quotes every mileage to a thousandth of a mile, and it quotes the two numbers
    compared below in different places: the floor once, and each fiber segment on its own,
    with the miles a synthesis ordered being those rounded segments added up. So a synthesis of
    many segments carries many roundings while the floor carries one, and the two can part
    company by that much with nothing whatever wrong. Two-Node landed exactly on its floor
    and published 3,884.264 miles against 3,884.265.

    Nothing real hides under this. A synthesis that genuinely falls short of its floor is short
    by at least the fiber it failed to buy, and the shortest segment on any of the five maps
    runs miles rather than thousandths.
    """
    segments = sum(1 for link in synthesis["paths"] if link["link_kind"] == FIBER)
    return (segments + 1) * _ROUNDED_TO / 2


def _tenants_outside(
    delivered_syntheses: list[dict[str, Any]],
    allowed: Callable[[float, float, float], bool],
) -> dict[str, tuple[float, float]]:
    """Every finished network whose ordered fiber miles sit outside what its floor allows.

    ``lower_bound_miles`` is the fewest miles any synthesis meeting that tenant's requirements
    could run, and the two questions asked of it below -- not too far above it, not below it
    at all -- are the same measurement read in opposite directions. Each finding names the
    tenant, the miles it ordered and the floor it ordered them against.

    A tenant whose build has not finished has no floor to be held to, so it is left out
    rather than compared against nothing.
    """
    measured = {
        synthesis["tenant"]: (
            ordered_fiber_miles(synthesis),
            synthesis["lower_bound_miles"],
            _rounding_slack(synthesis),
        )
        for synthesis in delivered_syntheses
        if synthesis["lower_bound_miles"] is not None
    }
    return {
        tenant: (miles, floor)
        for tenant, (miles, floor, slack) in measured.items()
        if not allowed(miles, floor, slack)
    }


def _published_cities(synthesis: dict[str, Any]) -> set[str]:
    """The cities the published backbone seats, by the ``City, ST`` names a config pins by."""
    return {node["name"] for node in synthesis["backbone"]}


def test_every_tenant_the_roster_declares_has_a_published_network(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """No tenant git declares is left without a WAN the synthesizer finished building."""
    unfinished = {
        synthesis["tenant"]: synthesis["status"].get("status")
        for synthesis in delivered_syntheses
        if synthesis["status"].get("status") != "success"
    }
    assert unfinished == {}


def test_every_published_network_is_one_network(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """The fiber a tenant ordered joins every backbone site it seated to all the others.

    A synthesis in two groups is two networks handed over as one, and the operator who
    receives it can carry no traffic between them. Nothing else in this file would notice:
    ``f-35`` sat in two halves with no fiber between Ashburn, VA and Salt Lake City, UT
    while passing every other assertion here, because each site met its diverse path count
    against peers inside its own half (GitHub issue #68).
    """
    split = {
        synthesis["tenant"]: groups
        for synthesis in delivered_syntheses
        if len(groups := backbone_groups(synthesis)) > 1
    }
    assert split == {}


def test_every_published_network_reports_the_coverage_it_delivered(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """A published status says what the synthesis did about its target, not only ``success``.

    That one word was all a reader outside the synthesizer used to get, and it read the same
    whether the coverage pass met the target or ran out of things to try.
    """
    silent = [
        synthesis["tenant"]
        for synthesis in delivered_syntheses
        if "coverage" not in synthesis["status"]
    ]
    assert silent == []


def test_every_report_is_measured_against_the_target_its_tenant_declares(
        delivered_syntheses: list[dict[str, Any]]) -> None:
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
        synthesis["tenant"]: synthesis["status"]["coverage"]["target_miles"]
        for synthesis in delivered_syntheses
    }
    declared = {synthesis["tenant"]: synthesis["target_miles"] for synthesis in delivered_syntheses}
    assert reported == declared


def test_every_city_a_tenant_pins_is_seated_in_its_published_backbone(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """Each city named in a tenant's ``backbone.forced.nodes`` is in its backbone tier.

    A pinned city is the one requirement an operator states as a plain fact about the
    finished network: put a backbone node here, whatever the coverage pass would rather do.
    Nothing outside the synthesizer checked that the fact came true, so a config that moved
    a pin and a network still seated on the old one read exactly alike -- which is how a
    change to this setting could pass this whole tier against a network built before it
    (GitHub issue #47).
    """
    unseated = {
        synthesis["tenant"]: sorted(set(synthesis["forced"]) - _published_cities(synthesis))
        for synthesis in delivered_syntheses
        if not set(synthesis["forced"]) <= _published_cities(synthesis)
    }
    assert unseated == {}


def test_the_reported_worst_haul_is_the_one_the_published_network_delivers(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """The worst haul a status claims is the worst haul its own published network has.

    Measured off the backbone and the sites as published, so the claim is checked against
    the artifact an operator reads rather than against the run that wrote it.
    """
    mismeasured = [
        (synthesis["tenant"], worst_haul(synthesis))
        for synthesis in delivered_syntheses
        if worst_haul(synthesis) != synthesis["status"]["coverage"]["worst_haul_miles"]
    ]
    assert mismeasured == []


def test_no_synthesis_stopped_short_of_its_target_with_a_seat_left_to_spend(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """A synthesis that ended below its coverage target had spent every seat it was allowed.

    This is the assertion the defect had to get past. Growth that halts with seats still
    free has decided no remaining candidate is worth taking, and on the old DAF build that
    decision was wrong twice over: sixteen seats used of ninety-nine, and every site the
    target applied to more than twice as far out as the target allowed.
    """
    gave_up_early = [
        (synthesis["tenant"], len(synthesis["backbone"]), synthesis["seat_cap"])
        for synthesis in delivered_syntheses
        if not synthesis["status"]["coverage"]["met"]
        and len(synthesis["backbone"]) < synthesis["seat_cap"]
    ]
    assert gave_up_early == []


def test_no_published_link_runs_further_than_its_tenant_allows(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """No backbone link wanders far past the direct distance between the two sites it joins.

    This is the assertion GitHub issue #44 had to get past. DAF's published network
    protected Ashburn to New York, 220 miles apart, along a 7,471-mile path through Paris,
    and protected Seattle to Hillsboro through Tokyo at 9,607 miles against 161 -- because
    the proof behind the mesh counted paths that share no city and read no distance at all.

    Measured against the great-circle distance rather than the shortest fiber path, since
    the published collections carry no fiber to draw over and rebuilding it here would
    reimplement the very code this layer exists to check from the outside. Great-circle is the
    shorter denominator, so the ratio it yields overstates the real multiple and the bound is
    loosened by ``SINUOSITY`` to stay sound. That leaves it far looser than what the
    synthesizer enforces -- six times the direct distance rather than three -- and it still
    catches every path the defect produced, the nearest of which ran twelve times.
    """
    overrun = {
        synthesis["tenant"]: overrun_links(synthesis)
        for synthesis in delivered_syntheses
        if overrun_links(synthesis)
    }
    assert overrun == {}


def test_no_published_link_wanders_past_the_fiber_its_own_network_carries(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """No backbone link runs far past the shortest way over the fiber the synthesis ordered.

    The assertion above measures each link against the straight line between its two sites,
    which is why it has to be loosened to six times the tenant's bound: real fiber does not
    fly. This one measures it against fiber -- the published ``links`` collection carries
    every fiber segment the synthesis ordered, so the shortest way between the two sites is
    recomputable from outside the build and the tenant's own ``max_backup_path_multiple`` can be
    applied to it without slack.

    What it cannot ask is whether the *set* of paths out of a site is the shortest set that
    holds that many independent links, which is what GitHub issue #57 is about: the proof
    behind the mesh chose the paths crossing the fewest cities rather than the ones running
    the fewest fiber miles, and a set of needlessly long paths can pass here with every link in it
    inside the bound. The paths proved and never drawn are not published at all. This is
    the strongest statement available from outside, and it needs nothing added to what the
    synthesizer publishes.
    """
    wandering = {
        synthesis["tenant"]: detoured_links(synthesis)
        for synthesis in delivered_syntheses
        if detoured_links(synthesis)
    }
    assert wandering == {}


def test_no_published_network_leaves_a_site_short_of_the_links_it_was_asked_for(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """No live tenant reports a site holding fewer independent links than it was asked for.

    A site is asked for the smaller of the tenant's own diverse-path number and the count of
    ways out its fiber proves, and the mesh then lays what it can. A count proved over
    paths the backup path multiple forbids asks for a link the mesh will not draw, and
    the site is reported short of it for the rest of the build's life -- a shortfall an
    operator reads, investigates and cannot close, because the missing link is one the
    bound itself refuses (GitHub issue #45).

    Read straight out of the status rather than guarded for, because a build that published
    no such finding is itself the failure this asks about: the shortfall appears nowhere in
    the collections, so a status that has stopped reporting it has taken the question away
    rather than answered it.
    """
    short = {
        synthesis["tenant"]: synthesis["status"]["diverse_paths"]["short"]
        for synthesis in delivered_syntheses
    }
    assert {tenant: sites for tenant, sites in short.items() if sites} == {}


def test_no_published_network_draws_a_pair_more_paths_than_its_tenant_bought(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """No two backbone sites are joined by a path that buys neither of them a path.

    Two sites that are joined are joined once, and a second path between them earns its
    monthly cost only where a single city's loss would not take it along with the first. So
    each pair's longest path is set aside and both ends are measured without it (see
    ``test_published_syntheses.overbuilt_pairs``): where neither end loses a way out it was
    asked for, nobody needed the path. Twenty-one pairs across DAF, F-35, Minuteman and
    AFGSC, which ``etc/`` no longer declares, were of that kind, 17,013 path miles of them,
    and passed here while this counted paths against the tenant's number instead (GitHub
    issue #59).

    The counterpart of the shortfall above, and the half that was missing. Every question
    this layer asked about paths asked it of one path at a time -- is this one inside the
    bound, is this one the shortest way over the fiber -- so a network could hold any number
    of them and answer yes every time. Two-Node did: five paths between Ashburn, VA and
    Salt Lake City, UT, each of them sound on its own, 5,633 miles of haul nobody ordered,
    and not one published measurement with anything to say about it (GitHub issue #58).

    Asked against the number in ``etc/`` rather than the one the build reported, because the
    question is whether the network an operator has is the network their config asks for.
    A build published before they last moved the number is measured against what they want
    now, which is the finding.
    """
    overbuilt = {
        synthesis["tenant"]: overbuilt_pairs(synthesis)
        for synthesis in delivered_syntheses
        if overbuilt_pairs(synthesis)
    }
    assert overbuilt == {}


def test_no_published_network_holds_a_path_that_buys_nobody_a_diverse_path(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """No published path could be taken out with every site and every city no worse off.

    A path is fiber the operator holds and pays for every month, and it earns that only
    where taking it out would cost somebody something: a backbone site the diverse paths
    its tenant asked for, a site its place in the one network the backbone is, or the
    fiber the standing it has against the loss of any one city. So each path is taken out
    in turn and what remains is put to those three demands (see
    ``test_published_syntheses.removable_paths``); a path all three still hold without is a
    path nobody needed.

    This is the assertion that would have reported the 54 paths against the six real maps
    there were then rather than against a fixture -- 23,917 of the 83,927 miles those six
    tenants paid for -- and it goes on reporting as the maps grow and tenants are added
    (GitHub issue #60).
    The nine questions asked before it each judge one path on its own: is this one inside
    the tenant's backup path multiple, is this one the shortest way over the fiber the
    synthesis ordered. A network can hold any number of unneeded paths and answer yes to every
    one of them. The tenth is the only one that judges a path against the rest of the
    synthesis, and it examines only pairs of sites holding more than one path between them
    (GitHub issue #59), while all 54 are the only path between their two sites, so it never
    looked at one of them.
    """
    spare = {synthesis["tenant"]: removable_paths(synthesis) for synthesis in delivered_syntheses}
    assert {tenant: paths for tenant, paths in spare.items() if paths} == {}


def test_no_published_network_is_split_by_the_loss_of_one_city(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """No tenant buying two ways out of every seat is handed a network one city's loss breaks.

    Two ways out of every backbone node is bought so that the backbone goes on carrying
    traffic when a city goes dark, and that is the thing the tenant is really paying for. It
    is not what a per-site count reports: a site keeps its own two ways out and still ends up
    cut off from most of its peers when the cities those peers depend on are the ones that
    failed. Three of the five live tenants were in that state and nothing they were handed
    said so -- the loss of Atlanta, GA left Ashburn, VA and New York, NY with no way to DAF's
    other nine backbone nodes, eight more cities split DAF somewhere else, four split
    Minuteman and Cheyenne, WY split DoW (GitHub issue #112).

    Asked of the cities each published path crosses (see
    ``test_published_syntheses.cut_cities``) rather than of the build's own
    ``backbone_mesh_survives_any_one_site_loss``, because that finding was already reporting
    ``False`` for all three of them and no assertion anywhere read it. A build that stops
    measuring the property is caught here; a build that measures it and publishes anyway is
    caught here too.

    A tenant asking for one diverse path is not asked this. Yurop asks for one, four cities
    split its network, and that is the honest answer to what it bought rather than a defect.
    """
    split = {
        synthesis["tenant"]: cut_cities(synthesis["links"])
        for synthesis in delivered_syntheses
        if synthesis["number_of_diverse_paths"] >= 2
    }
    assert {tenant: cities for tenant, cities in split.items() if cities} == {}


def test_no_published_network_runs_more_than_twice_the_fewest_miles_it_could_have(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """Every published network ordered at most twice the fiber miles it could have ordered.

    Each build publishes the floor its own synthesis is judged against. ``lower_bound_miles``
    is the optimum of the linear-programming relaxation the build solved, which is the
    fewest miles of fiber any synthesis meeting the same tenant's requirements could run, and
    holding the fiber the synthesis ordered against it turns "the synthesis is close to the
    shortest one there is" from a claim about an algorithm into a statement a test can make
    on the five real maps (GitHub issue #60).

    That is the half an approximation cannot report about itself. The factor of two is a
    property of the method rather than of the code that runs it, so an implementation that
    has lost the guarantee through a defect goes on publishing syntheses that look perfectly
    well formed from every other angle -- which is how 54 paths buying nobody a diverse
    path stayed invisible from out here. This is where it shows, and the finding names the
    tenant, the miles it ordered and the floor it ordered them against.
    """
    assert _tenants_outside(
        delivered_syntheses, lambda miles, floor, _slack: miles <= 2 * floor
    ) == {}


def test_no_published_network_runs_fewer_miles_than_the_floor_it_publishes(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """Every published network ordered at least the fiber miles it says no synthesis can go below.

    ``lower_bound_miles`` is the fewest miles any synthesis meeting that tenant's requirements
    could run, so a synthesis below it is not a synthesis that came in under target -- it is
    arithmetic that has come apart, and the only thing it can mean is that the synthesis does
    not meet the requirements it was built for. An operator reading such a network has been
    handed one that does not do what they asked, with nothing on it saying so.

    This is the direction the assertion above does not test, and the two are not
    interchangeable. That one fires when a synthesis runs too long, and it caught Two-Node at
    2.078 times its floor.

    It is held to the precision the two numbers are published at, which ``_rounding_slack``
    works out. Two-Node and Minuteman both land exactly on their floors now and both publish
    a total one thousandth of a mile under them, because the floor is rounded once and the
    ordered miles are rounded segment by segment and then added up. Landing on the floor is
    the best a synthesis can do, so reading that as a shortfall would fail the very networks
    this exists to pass.

    What it can catch is bounded by which floor a tenant publishes, and that is worth being
    exact about. Both numbers come out of the same search, so while the search was being cut
    off early the published floor was too low and moved with the synthesis that was too small:
    F-35 published 6,664.009 miles against a published floor of 6,359.323 and passes here,
    though a finished search floors it at 7,772.795 and the delivered synthesis was 1,108.786
    miles below the fewest miles any working synthesis could hold. So this would not have
    caught F-35 as it stood, and GitHub issue #63 was wrong to say it would. It bites from
    the moment that search is allowed to finish, because the floor a tenant publishes is
    then the real one and a synthesis under it is arithmetic that has come apart.
    """
    assert _tenants_outside(
        delivered_syntheses, lambda miles, floor, slack: miles >= floor - slack
    ) == {}


def _city_names() -> dict[tuple[str, str], str]:
    """Every city the carriers have a point in, under the name a published hop carries.

    A fiber row names its two ends by municipality and state, and a published hop names a
    city the way an operator pins one: ``City, ST`` for a place in the United States and
    ``City, Country`` everywhere else. The country is in ``data/pops/*.csv`` and not in the
    fiber files, so the two are read together here -- the same join
    ``synthesizer.codec.load_merged_carriers`` makes when it resolves a fiber row against
    the points the carriers hold.
    """
    named: dict[tuple[str, str], str] = {}
    for path in sorted((seed.DATA / "pops").glob("*.csv")):
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                region = (
                    row["State"] if row["Country"] == "United States" else row["Country"]
                )
                named[(row["Municipality"], row["State"])] = (
                    f"{row['Municipality']}, {region}"
                )
    return named


def _fiber_by_carrier() -> dict[str, set[frozenset[str]]]:
    """Which city pairs each carrier has fiber between, as the published links spell them.

    Read from ``data/fiber_segments/*.csv``, the files ``scripts/seed.py`` pushes, and
    keyed by the name a published hop carries. A pair is order-independent: a length of
    fiber is the same fiber whichever way a path runs over it.

    A row naming a city no carrier has a point in is left out, which is what the build does
    with it too: such a row resolves against nothing and never reaches the merged map.
    """
    named = _city_names()
    held: dict[str, set[frozenset[str]]] = {}
    for path in sorted((seed.DATA / "fiber_segments").glob("*.csv")):
        pairs: set[frozenset[str]] = set()
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                near = named.get((row["A_Municipality"], row["A_State"]))
                far = named.get((row["Z_Municipality"], row["Z_State"]))
                if near and far:
                    pairs.add(frozenset({near, far}))
        held[path.stem] = pairs
    return held


def _anybodys_fiber(held: dict[str, set[frozenset[str]]]) -> set[frozenset[str]]:
    """Every city pair some carrier has fiber between, whoever it is."""
    everyone: set[frozenset[str]] = set()
    for pairs in held.values():
        everyone |= pairs
    return everyone


def _hops(link: dict[str, Any]) -> list[frozenset[str]]:
    """Every length of fiber one published path runs over, as order-independent city pairs."""
    cities = link.get("path") or []
    return [frozenset({left, right}) for left, right in zip(cities, cities[1:])]


def _paths_changing_hands(syntheses: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Per tenant, every published path holding a length of fiber its own carrier lacks.

    A hop no carrier's file holds at all is a synthetic lateral the operator lays into a
    fabricated site, and rules nobody out; a hop some carrier has and the named one does
    not is fiber the tenant has been sold by a company that has none there.
    """
    held = _fiber_by_carrier()
    anybody = _anybodys_fiber(held)
    found: dict[str, list[str]] = {}
    for synthesis in syntheses:
        for link in synthesis["links"]:
            mine = held.get(link.get("carrier", ""), set())
            if any(hop in anybody and hop not in mine for hop in _hops(link)):
                found.setdefault(synthesis["tenant"], []).append(
                    f"{link['source_name']} to {link['target_name']}"
                )
    return found


def _paths_naming_no_carrier(syntheses: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Per tenant, every published path over a carrier's fiber that names no carrier."""
    anybody = _anybodys_fiber(_fiber_by_carrier())
    found: dict[str, list[str]] = {}
    for synthesis in syntheses:
        for link in synthesis["links"]:
            if not link.get("carrier") and any(hop in anybody for hop in _hops(link)):
                found.setdefault(synthesis["tenant"], []).append(
                    f"{link['source_name']} to {link['target_name']}"
                )
    return found


def test_no_published_path_changes_carrier_partway_along_itself(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """Every published path is fiber one company has all of, so somebody can quote it.

    A path is what an operator orders and pays for every month, and it is ordered from one
    carrier. Half of one company's fiber spliced to half of another's is not a product
    anybody sells, so a tenant handed such a path has been handed a network they cannot
    buy -- and nothing else out here would say so, because every hop of it is real fiber
    between real cities. Measured against the carrier files git holds rather than against
    the build's own account of itself.
    """
    assert not _paths_changing_hands(delivered_syntheses)


def test_every_published_path_over_a_carriers_fiber_names_that_carrier(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """A tenant reading their network can see who to call for each path in it.

    A path with no carrier on it is one the tenant cannot order, however sound its
    geometry. The exception is a path running only over the synthetic lateral fiber a
    fabricated site is wired on, which no carrier has and which names nobody correctly, so
    only the paths crossing fiber some carrier does hold are asked.
    """
    assert not _paths_naming_no_carrier(delivered_syntheses)


def _tenants_fiber(synthesis: dict[str, Any]) -> dict[str, set[frozenset[str]]]:
    """The fiber each carrier could sell this tenant a path over, as city pairs.

    Every carrier's own file, plus the synthetic lateral fiber the operator lays into a
    fabricated site. That fiber is nobody's, so every carrier's path may run over it, which
    is the rule ``synthesizer.graphs.adjacency_by_carrier`` applies to a segment naming no
    carrier. It is read off the tenant's own published links, since the carrier files
    record none of it.
    """
    held = _fiber_by_carrier()
    anybody = _anybodys_fiber(held)
    laid = {
        hop for link in synthesis["links"] for hop in _hops(link) if hop not in anybody
    }
    return {carrier: pairs | laid for carrier, pairs in held.items()}


def _cities_with_fiber(held: dict[str, set[frozenset[str]]]) -> set[str]:
    """Every city some carrier's fiber reaches, whoever it is."""
    return {city for pair in _anybodys_fiber(held) for city in pair}


def _paths_one_peer_may_end(synthesis: dict[str, Any]) -> int:
    """How many of a site's ways out one peer may end, given the seats the config allows.

    One wherever the config allows peers enough to reach instead, and above one where it
    does not: a backbone capped at two seats has one peer to reach, so a tenant asking for
    two ways out can only be answered by two paths to it. This is
    ``synthesizer.ceiling.paths_per_peer`` worked out from the tenant's own config rather
    than read off the build.
    """
    peers = synthesis["seat_cap"] - 1
    asked = synthesis["number_of_diverse_paths"]
    return max(1, -(-asked // peers)) if peers > 0 else 1


def _overstated_ceilings(syntheses: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Per tenant, every published ceiling above what its carriers could be asked to quote.

    A site the carriers' fiber does not reach at all is left out rather than reported at
    nothing: no file records the fiber it stands on, so there is nothing out here to hold
    its ceiling against.
    """
    found: dict[str, list[str]] = {}
    for synthesis in syntheses:
        held = _tenants_fiber(synthesis)
        reached = _cities_with_fiber(held)
        cities = _published_cities(synthesis)
        per_peer = _paths_one_peer_may_end(synthesis)
        for entry in synthesis["status"].get("diverse_paths", {}).get("ceilings", []):
            city = str(entry["name"])
            if city not in reached:
                continue
            sellable = sellable_ways_out(
                held, city, frozenset(cities - {city}), per_peer
            )
            if int(entry["ceiling"]) > sellable:
                found.setdefault(synthesis["tenant"], []).append(
                    f"{city} at {entry['ceiling']} against {sellable}"
                )
    return found


def test_no_published_networks_ceiling_is_higher_than_the_paths_its_carriers_can_sell(
        delivered_syntheses: list[dict[str, Any]]) -> None:
    """Every ceiling a build published is one its carriers could between them be asked to quote.

    A ceiling is what a site could hold, and every target the build holds a site to is the
    smaller of that and the tenant's number, so a ceiling too high asks a site for a way out
    nobody sells and prices the floor beside it for one too. Yurop published 8,844.892 miles
    against a floor of 9,141.641 it had already beaten, because Boston, MA was counted for
    two ways out where Zayo, Lumen and Cogent hold one apiece and only Zayo's reaches
    anywhere else Yurop pins (GitHub issue #111).

    This is the assertion that names the figure rather than the network. The two mileages
    the tier already holds against each other both come out of the same build, so a
    disagreement between them says only that one of the two is wrong; recomputing the
    ceilings from ``data/fiber_segments/*.csv`` and ``data/pops/*.csv`` one carrier at a
    time is a second source, and it says which.

    Recomputed generously on purpose: each carrier is asked on its own and the answers are
    added, though two carriers' answers may cross the same city and a city carrying two
    ways out is one way out the moment it goes. What is being asked is whether a published
    ceiling is above anything anybody could sell, so the direction that errs leaves a sound
    ceiling passing rather than failing a healthy network.
    """
    assert not _overstated_ceilings(delivered_syntheses)
