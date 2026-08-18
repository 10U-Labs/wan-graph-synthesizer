"""Choose the fiber a whole backbone is built from at once, and say how short it could be.

A tenant asks for a number of ways out of every backbone node that no one city's loss
takes two of. Which segments of the carrier's fiber to buy so that every node has them is
one question about the whole design, and this module answers it as one question rather
than as a sequence of decisions about one pair of sites at a time. Deciding a pair at a
time is what left 54 of the 192 published paths buying nobody a way out, 23,917 miles of
fiber that six tenants pay for every month and get nothing for (GitHub issue #60): each
decision was defensible when it was taken and none of them was ever revisited.

The problem has a name. Choosing the fewest-mile set of fiber segments in which every pair
of backbone nodes is joined by as many paths sharing no city as the tenant asked for is
the survivable network design problem, and it is NP-hard -- the case where every
requirement is two contains Hamiltonian cycle -- so no exact method finishes on a national
map. What is available is a method with a proven limit on how far past the ideal it can
land, by iterative rounding of the linear-programming relaxation: hold each segment
anywhere between none of it and all of it, buy the fewest miles that meet every
requirement, and take the segments the answer holds at half or more as bought outright
(Fleischer, Jain and Williamson 2006, on the half-integrality of Jain 2001). Repeat over
what is still unmet. For element connectivity -- paths sharing no fiber segment and no
city between their two ends -- that lands within twice the fewest miles any design could
have run.

The relaxation is where the second half of the answer comes from. No design can run fewer
miles than a program whose every row is a requirement that design has to meet, so the
program's own answer is a floor under the whole problem. It is published beside the design
as ``backbone_lower_bound_miles``, because a claim that a design is close to the shortest
one there is means nothing until the shortest one there is has a number.

Two requirements are written down rather than one, and they are not the same requirement.
Element connectivity between every pair of backbone nodes is the one the bound above is
proved for, and it treats the sites at a path's two ends as never failing. What this
repository actually asks of a site is narrower: ``synthesizer.validation.
diverse_path_count`` charges a way out for the peer it ends at, so two ways out of a site
that both run through one peer are one way out rather than two. That requirement is
written down as well, once per site, and the fiber has to meet both. Writing only the
first would let the program buy a design where every way out of a site runs through one of
its peers, which the tenant did not ask for and validation would refuse.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace

from synthesizer.ceiling import BackupPathLimit
from synthesizer.flow_cuts import Separation, SeparationQuestion, weakest_separation
from synthesizer.input_graph import PhysicalEdge
from synthesizer.linear_program import SegmentChoice, SegmentProgram, SegmentRow, solve

# How many times a program is re-solved to look for requirements its answer still misses
# before a round settles for what it has. Each pass costs one solve and one search per
# requirement, and the passes stop on their own as soon as a pass finds nothing; the cap is
# there so a program whose answer keeps moving by fractions cannot hold a build open.
_SEPARATION_PASSES = 24

# What counts as holding a segment outright. Half of it is the share Jain's half-integrality
# result guarantees some segment reaches, and taking those is what makes the finished choice
# at most twice the fewest miles any design could have run.
_HELD_OUTRIGHT = 0.5

# Slack in miles, absorbing the rounding of a sum of great-circle distances and the
# arithmetic of a solved program. Five millimetres, so it admits no real fiber segment.
_TOLERANCE = 1e-6


@dataclass(frozen=True)
class FiberInputs:
    """The fiber a design may be built from and what the tenant asks it to carry.

    ``ways_out`` is the tenant's ``number_of_diverse_paths``, asked of every backbone node
    and of every pair of them. ``per_peer`` is how many of a site's ways out one peer may
    take, which is one wherever the tenant's config allows peers enough to reach instead
    (see :func:`synthesizer.ceiling.paths_per_peer`); above one, a peer stops being a city
    a way out is charged for and becomes a destination two ways out may share. ``limit`` is
    the operator's backup path multiple, which decides which of the carrier's fiber an
    admissible path could run over at all.
    """

    backbone_ids: tuple[str, ...]
    physical_edges: Mapping[tuple[str, str], PhysicalEdge]
    all_distances: Mapping[str, Mapping[str, float]]
    ways_out: int = 3
    per_peer: int = 1
    limit: BackupPathLimit | None = None


@dataclass(frozen=True)
class FiberChoice:
    """The fiber a design is built from, beside the fewest miles any design could run.

    ``lower_bound_miles`` is the relaxation's own answer over every requirement the search
    wrote down, so no design meeting those requirements runs fewer miles than this.
    """

    segments: frozenset[tuple[str, str]]
    lower_bound_miles: float


@dataclass(frozen=True)
class _Requirement:
    """One thing the fiber must do: this many ways from this site to these peers.

    ``spared`` are the cities that cannot fail while the ways are counted -- the site
    itself always, and the peers as well where a peer is a destination rather than a city
    a way out is charged for.
    """

    site: str
    peers: frozenset[str]
    spared: frozenset[str]
    required: int


@dataclass(frozen=True)
class _BudgetSlack:
    """How far a path from one site reaches each city, and what budget it has left there.

    ``reach`` is the shortest way from the site to each city. ``spare`` is the least, over
    the site's peers, of what carrying on from that city to a peer costs less that peer's
    budget -- so a city whose ``spare`` plus the site's ``reach`` comes to more than
    nothing sits on no path out of that site the backup path multiple allows.
    """

    reach: Mapping[str, float]
    spare: Mapping[str, float]


@dataclass
class _Search:
    """The program as it stands, beside the fiber it is written over and what it has bought.

    The rows only ever grow: a separation the fiber could not survive at one point in the
    search is a separation no later answer may ignore, so every row found is carried into
    every later solve.
    """

    order: list[tuple[str, str]]
    column: dict[tuple[str, str], int]
    miles: tuple[float, ...]
    rows: list[SegmentRow]
    bought: frozenset[tuple[str, str]]


def _slack_from(site: str, inputs: FiberInputs, limit: BackupPathLimit) -> _BudgetSlack:
    """What every city costs a path out of ``site``, measured against its peers' budgets."""
    rows = limit.distances
    from_site = rows.get(site, {})
    budgets = [
        (peer, limit.multiple * from_site[peer])
        for peer in inputs.backbone_ids
        if peer != site and math.isfinite(from_site.get(peer, math.inf))
    ]
    spare = {
        city: min(
            (rows.get(peer, {}).get(city, math.inf) - budget for peer, budget in budgets),
            default=math.inf,
        )
        for city in inputs.all_distances
    }
    return _BudgetSlack(from_site, spare)


def _reaches(segment: tuple[str, str], length: float, slack: _BudgetSlack) -> bool:
    """Whether one site could run an admissible path over this segment, either way round."""
    left, right = segment
    return any(
        slack.reach.get(near, math.inf) + length + slack.spare.get(far, math.inf) <= _TOLERANCE
        for near, far in ((left, right), (right, left))
    )


def admissible_fiber(inputs: FiberInputs) -> dict[tuple[str, str], float]:
    """The carrier fiber a path between two backbone nodes could run over inside the bound.

    A segment from ``u`` to ``v`` can lie on a path from site ``a`` to peer ``b`` no longer
    than that pair's budget only when ``d(a,u) + len(u,v) + d(v,b)`` fits inside it. A
    segment failing that for every site and every peer, in both of its orientations, is
    fiber no admissible path can use, and leaving it out of the choice is what stops the
    program buying an ocean crossing to protect a state line (GitHub issue #44).

    With no bound in hand every segment is admissible, which is the behaviour of every
    caller with no tenant to be measured against.
    """
    miles = {
        segment: edge.distance_miles for segment, edge in inputs.physical_edges.items()
    }
    if inputs.limit is None:
        return miles
    slacks = [_slack_from(site, inputs, inputs.limit) for site in inputs.backbone_ids]
    return {
        segment: length
        for segment, length in miles.items()
        if any(_reaches(segment, length, slack) for slack in slacks)
    }


def _ways_out_requirement(site: str, inputs: FiberInputs) -> _Requirement:
    """What one site is owed: as many ways out as the tenant asked, ending at its peers."""
    peers = frozenset(inputs.backbone_ids) - {site}
    spared = frozenset({site}) if inputs.per_peer == 1 else frozenset({site}) | peers
    return _Requirement(site, peers, spared, inputs.ways_out)


def _between_requirement(root: str, peer: str, inputs: FiberInputs) -> _Requirement:
    """What one pair is owed: as many paths between them as share no city on the way.

    Every backbone node is spared here and not only the two ends, which is what makes this
    element connectivity -- the requirement the fewest-mile bound is proved for. It is
    written from one site to each of the others rather than between every pair: what it
    takes to separate two sites is never less than the smaller of what it takes to separate
    each of them from a third, so holding one site to every peer holds every pair.
    """
    return _Requirement(root, frozenset({peer}), frozenset(inputs.backbone_ids), inputs.ways_out)


def _question(
    requirement: _Requirement, held: Mapping[tuple[str, str], float]
) -> SeparationQuestion:
    """The requirement asked of fiber held in the shares given."""
    return SeparationQuestion(requirement.site, requirement.peers, requirement.spared, held)


def _capped(requirement: _Requirement, whole: Mapping[tuple[str, str], float]) -> _Requirement:
    """The same requirement, lowered to what the carrier's fiber can actually carry.

    A site behind a single point of failure on the carrier's fiber cannot be given two ways
    out by any amount of buying, so asking for two would leave the program with no answer
    at all rather than with the honest one. Lowering it here is what keeps every row the
    program is given a row some design can meet, and the shortfall is then reported by
    ``synthesizer.validation.backbone_mesh_independence_deficient`` rather than hidden.
    """
    required = requirement.required
    while required > 0 and weakest_separation(_question(requirement, whole), required):
        required -= 1
    return replace(requirement, required=required)


def _requirements(
    inputs: FiberInputs, fiber: Mapping[tuple[str, str], float]
) -> list[_Requirement]:
    """Everything the fiber has to do, each already lowered to what the carrier can carry.

    One requirement per site for the ways out it is owed, and one per peer of the
    best-served site for the paths between them. The site the pairwise requirements are
    written from is the one the carrier's fiber serves best, since holding every pair to
    what the weakest site can manage would spend the whole backbone's protection on one
    node's shortfall.
    """
    whole = {segment: 1.0 for segment in fiber}
    ways_out = [
        _capped(_ways_out_requirement(site, inputs), whole) for site in inputs.backbone_ids
    ]
    if not ways_out:
        return []
    root = min(ways_out, key=lambda owed: (-owed.required, owed.site)).site
    return ways_out + [
        _capped(_between_requirement(root, peer, inputs), whole)
        for peer in sorted(set(inputs.backbone_ids) - {root})
    ]


def _shortfalls(
    requirements: list[_Requirement], held: Mapping[tuple[str, str], float]
) -> list[tuple[Separation, int]]:
    """Every requirement this much fiber does not meet, as the separation that shows it."""
    found: list[tuple[Separation, int]] = []
    for requirement in requirements:
        separation = weakest_separation(_question(requirement, held), requirement.required)
        if separation is not None:
            found.append((separation, requirement.required))
    return found


def _rows(
    shortfalls: list[tuple[Separation, int]], column: Mapping[tuple[str, str], int]
) -> list[SegmentRow]:
    """Each separation written as the row it is: hold this much of the fiber that crosses it."""
    return [
        SegmentRow(
            tuple(sorted(column[segment] for segment in separation.crossing_segments)),
            float(required - len(separation.lost_cities)),
        )
        for separation, required in shortfalls
    ]


def _held(
    fiber: Mapping[tuple[str, str], float], bought: frozenset[tuple[str, str]]
) -> dict[tuple[str, str], float]:
    """How much of each candidate segment is held once ``bought`` is taken outright."""
    return {segment: 1.0 if segment in bought else 0.0 for segment in fiber}


def _shares(
    choice: SegmentChoice, order: list[tuple[str, str]]
) -> dict[tuple[str, str], float]:
    """The solver's answer read back as a share of each fiber segment."""
    return dict(zip(order, choice.held))


def _solve_search(search: _Search, fix: bool) -> SegmentChoice:
    """Solve the program as it stands, with what has been bought held outright or not.

    Holding the bought segments outright is what the rounding needs: each round asks what
    the fewest miles are given the choices already made. Letting them go is what the
    published floor needs, since a floor under the whole problem may take nothing about
    this particular search for granted.
    """
    bought = frozenset(search.column[segment] for segment in search.bought) if fix else frozenset()
    return solve(SegmentProgram(search.miles, bought, tuple(search.rows)))


def _tighten(search: _Search, requirements: list[_Requirement]) -> SegmentChoice:
    """Solve, look for a requirement the answer misses, write it down, and solve again.

    There is one requirement for every way of separating a site from its peers, far too
    many to write out, so they are written down as an answer violates them: solve with the
    rows so far, search each requirement over the shares that came back, add what that
    found, and solve again. It settles as soon as a pass finds nothing, which is the point
    at which the answer meets every requirement there is and not only the ones on paper.
    """
    passes = _SEPARATION_PASSES
    choice = _solve_search(search, fix=True)
    shortfalls = _shortfalls(requirements, _shares(choice, search.order))
    while shortfalls and passes:
        passes -= 1
        search.rows.extend(_rows(shortfalls, search.column))
        choice = _solve_search(search, fix=True)
        shortfalls = _shortfalls(requirements, _shares(choice, search.order))
    return choice


def _round_up(search: _Search, choice: SegmentChoice) -> frozenset[tuple[str, str]]:
    """The segments this round buys outright: every one the answer holds at half or more.

    Jain's result says a fewest-miles answer always holds some segment at half or more, so
    a round always buys something and the search always ends. The fallback is for the
    arithmetic rather than the mathematics: the two requirements written here are not the
    single family that result is proved for, so where an answer holds nothing that high the
    round buys the segment it holds most of, which keeps the search finite either way.
    """
    shares = _shares(choice, search.order)
    left = [
        (share, segment) for segment, share in shares.items() if segment not in search.bought
    ]
    fresh = frozenset(
        segment for share, segment in left if share >= _HELD_OUTRIGHT - _TOLERANCE
    )
    return fresh or frozenset({max(left)[1]})


def choose_fiber(inputs: FiberInputs) -> FiberChoice:
    """The fiber to build this backbone from, and the fewest miles any design could run.

    Rounds of buying, each one a fewest-miles answer over every requirement written down so
    far with the earlier rounds' segments held outright, until the fiber bought meets every
    requirement on its own. Then one last answer with nothing held outright, which is the
    floor: no design meeting these requirements runs fewer miles than that.

    A backbone the carrier's fiber says nothing about buys nothing and is floored at
    nothing, which is the truth about it -- there is no fiber to choose from, so the
    shortfall belongs to the report rather than to a program with no columns.
    """
    fiber = admissible_fiber(inputs)
    if not fiber:
        return FiberChoice(frozenset(), 0.0)
    requirements = _requirements(inputs, fiber)
    order = sorted(fiber)
    search = _Search(
        order,
        {segment: index for index, segment in enumerate(order)},
        tuple(fiber[segment] for segment in order),
        [],
        frozenset(),
    )
    while True:
        shortfalls = _shortfalls(requirements, _held(fiber, search.bought))
        if not shortfalls:
            break
        search.rows.extend(_rows(shortfalls, search.column))
        search.bought |= _round_up(search, _tighten(search, requirements))
    return FiberChoice(search.bought, _solve_search(search, fix=False).miles)
