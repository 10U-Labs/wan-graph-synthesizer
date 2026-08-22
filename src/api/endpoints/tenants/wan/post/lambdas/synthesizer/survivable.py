"""Choose the fiber a whole backbone is built from at once, and say how short it could be.

A tenant asks for a number of ways out of every backbone node that no one city's loss
takes two of. Which segments of the carrier's fiber to buy so that every node has them is
one question about the whole synthesis, and this module answers it as one question rather
than as a sequence of decisions about one pair of sites at a time. Deciding a pair at a
time is what left 54 of the 192 published paths buying nobody a way out, 23,917 miles of
fiber that the six tenants declared then paid for every month and got nothing for (GitHub
issue #60): each decision was defensible when it was taken and none was ever revisited.

The problem has a name. Choosing the fewest-mile set of fiber segments in which every pair
of backbone nodes is joined by as many paths sharing no city as the tenant asked for is
the survivable network synthesis problem, and it is NP-hard -- the case where every
requirement is two contains Hamiltonian cycle -- so no exact method finishes on a national
map. What is available is a method with a proven limit on how far past the ideal it can
land, by iterative rounding of the linear-programming relaxation: hold each segment
anywhere between none of it and all of it, buy the fewest miles that meet every
requirement, and take the segments the answer holds at half or more as bought outright
(Fleischer, Jain and Williamson 2006, on the half-integrality of Jain 2001). Repeat over
what is still unmet. For element connectivity -- paths sharing no fiber segment and no
city between their two ends -- that lands within twice the fewest miles any synthesis could
have run.

The relaxation is where the second half of the answer comes from. No synthesis can run fewer
miles than a program whose every row is a requirement that synthesis has to meet, so the
program's own answer is a floor under the whole problem. It is published beside the synthesis
as ``backbone_lower_bound_miles``, because a claim that a synthesis is close to the shortest
one there is means nothing until the shortest one there is has a number.

What a site can be given is what one carrier can sell it, and no further than the operator
would order. A path is bought from one company end to end and paid for every month, so two
ways out of a site whose halves belong to different companies are one way out and not two;
and a path running further from the straight line than the tenant's
``backbone.max_backup_path_multiple`` allows is one nobody orders at all. Every requirement
below is therefore written over one carrier's own fiber, cut to the segments a path from
that site to those peers could run on inside that bound, and the tenant's number is spread
over the carriers by :func:`synthesizer.ceiling.ways_out_by_carrier` -- the same proof
:func:`synthesizer.stages.finalize` later holds the finished synthesis to.

Writing them over the whole map instead is what made the fiber chosen here beside the
point. The answer met requirements with ways out nobody sells and detours nobody would
order, ``synthesizer.backbone._ways_out_of`` then drew 29 of the 37 backbone seats over the
carriers' whole fiber rather than over what was bought, and the floor published beside the
synthesis was a floor for a network no operator could have built: DoW ran 9,294.692 miles
against 7,361.252 (GitHub issue #113). The narrower half of the same defect had already
been answered for the floor alone by lowering each requirement to a ceiling, after Yurop
published 8,844.892 miles against a floor of 9,141.641 it had already beaten (GitHub issue
#111).

Two requirements are written down rather than one, and they are not the same requirement.
Element connectivity between every pair of backbone nodes is the one the bound above is
proved for, and it treats the sites at a path's two ends as never failing. What this
repository actually asks of a site is narrower: ``synthesizer.validation.
diverse_path_count`` charges a way out for the peer it ends at, so two ways out of a site
that both run through one peer are one way out rather than two. That requirement is
written down as well, once per site, and the fiber has to meet both. Writing only the
first would let the program buy a synthesis where every way out of a site runs through one of
its peers, which the tenant did not ask for and validation would refuse.

Splitting the rows by carrier costs the bound nothing. A synthesis meeting rows that each
name one company is a synthesis meeting the same rows written over everybody's fiber at
once, so the relaxation's answer is still below anything buildable and
``backbone_lower_bound_miles`` is still a floor. What changes is which network it is a
floor for: the one the tenant is handed, rather than one nobody could have ordered.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

from synthesizer.ceiling import (
    BackupPathLimit,
    PathProofInputs,
    paths_per_peer,
    ways_out_by_carrier,
)
from synthesizer.flow_cuts import Separation, SeparationQuestion, weakest_separation
from synthesizer.graphs import build_adjacency
from synthesizer.input_graph import FiberSegment
from synthesizer.linear_program import GrowingSegmentProgram, SegmentChoice, SegmentRow

# What counts as holding a segment outright. Half of it is the share Jain's half-integrality
# result guarantees some segment reaches, and taking those is what makes the finished choice
# at most twice the fewest miles any synthesis could have run.
_HELD_OUTRIGHT = 0.5

# Slack in miles, absorbing the rounding of a sum of great-circle distances and the
# arithmetic of a solved program. Five millimetres, so it admits no real fiber segment.
_TOLERANCE = 1e-6


@dataclass(frozen=True)
class FiberInputs:
    """The fiber a synthesis may be built from and what the tenant asks it to carry.

    ``ways_out`` is the tenant's ``number_of_diverse_paths``, asked of every backbone node
    and of every pair of them. ``seat_cap`` is the most backbone sites the tenant's config
    allows, which is ``backbone.node_count.max`` in its ``etc/`` file; it decides how many
    of a site's ways out one peer may take (see
    :func:`synthesizer.ceiling.paths_per_peer`), which is one wherever the config allows
    peers enough to reach instead and above one where it does not, and there a peer stops
    being a city a way out is charged for and becomes a destination two ways out may share.
    ``limit`` is the operator's backup path multiple, which decides which of the carrier's
    fiber an admissible path could run over at all.

    ``fiber_by_carrier`` is the same fiber split into what each carrier could sell a path
    over (see :func:`synthesizer.graphs.adjacency_by_carrier`). An operator orders a path
    from one carrier, so what a site can be given is what one carrier can sell it, and every
    requirement is written over one of these shares (see :func:`_fiber_by_carrier`). Empty
    is fiber that names no carrier, which every carrier's path may run over.
    """

    backbone_ids: tuple[str, ...]
    fiber_segments: Mapping[tuple[str, str], FiberSegment]
    all_distances: Mapping[str, Mapping[str, float]]
    ways_out: int = 3
    seat_cap: int | None = None
    limit: BackupPathLimit | None = None
    fiber_by_carrier: dict[str, dict[str, list[tuple[str, float]]]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class FiberChoice:
    """The fiber a synthesis is built from, beside the fewest miles any synthesis could run.

    ``lower_bound_miles`` is the relaxation's own answer over every requirement the search
    wrote down, so no synthesis meeting those requirements runs fewer miles than this.
    """

    segments: frozenset[tuple[str, str]]
    lower_bound_miles: float


@dataclass(frozen=True)
class _Requirement:
    """One thing the fiber must do: this many ways from this site to these peers.

    ``spared`` are the cities that cannot fail while the ways are counted -- the site
    itself always, and the peers as well where a peer is a destination rather than a city
    a way out is charged for.

    ``over`` is the fiber this requirement may be met with, and it is what makes the row a
    row somebody can buy. An operator orders a path from one company end to end and no
    further than their backup path multiple allows, so a requirement is written over one
    carrier's segments, cut to the ones a path from this site to these peers could run on
    inside that bound. A requirement written over the whole map instead is answered by ways
    out nobody sells and detours nobody would order, and the drawing then refuses to count
    them (GitHub issue #113).
    """

    site: str
    peers: frozenset[str]
    spared: frozenset[str]
    required: int
    over: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class _Writing:
    """What every requirement is written against, worked out once for the whole program.

    ``fiber`` is the admissible fiber and ``by_carrier`` is it split into what each company
    could sell a path over. ``whole`` is that fiber held outright, which is what a
    requirement is lowered against: a row no amount of buying could answer is a search that
    never ends rather than a synthesis with an honest shortfall in it. ``per_peer`` is how
    many of a site's ways out one peer may take and ``proof`` is what
    :func:`synthesizer.ceiling.ways_out_by_carrier` is asked with.
    """

    inputs: FiberInputs
    fiber: Mapping[tuple[str, str], float]
    by_carrier: Mapping[str, frozenset[tuple[str, str]]]
    whole: Mapping[tuple[str, str], float]
    per_peer: int
    proof: PathProofInputs


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
    every later solve. ``written`` is which of them the program is already holding, since
    the same separation is found again and again as the answer moves and a row a second
    time constrains nothing while costing a solve and a search on every later pass.
    """

    order: list[tuple[str, str]]
    column: dict[tuple[str, str], int]
    program: GrowingSegmentProgram
    written: set[tuple[tuple[int, ...], float]]
    bought: frozenset[tuple[str, str]]


def _slack_from(
    site: str, inputs: FiberInputs, limit: BackupPathLimit, peers: Iterable[str]
) -> _BudgetSlack:
    """What every city costs a path out of ``site``, measured against those peers' budgets.

    ``peers`` is which of them the paths may end at. Asked of every backbone node it says
    which fiber any admissible path could use, which is what :func:`admissible_fiber`
    wants; asked of one peer it says which fiber a path to that peer could use, which is
    the sharper question a single requirement is written over.
    """
    rows = limit.distances
    from_site = rows.get(site, {})
    budgets = [
        (peer, limit.multiple * from_site[peer])
        for peer in peers
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
        segment: link.distance_miles for segment, link in inputs.fiber_segments.items()
    }
    if inputs.limit is None:
        return miles
    slacks = [
        _slack_from(site, inputs, inputs.limit, inputs.backbone_ids)
        for site in inputs.backbone_ids
    ]
    return {
        segment: length
        for segment, length in miles.items()
        if any(_reaches(segment, length, slack) for slack in slacks)
    }


def _within_budget(
    inputs: FiberInputs,
    fiber: Mapping[tuple[str, str], float],
    site: str,
    peers: frozenset[str],
) -> frozenset[tuple[str, str]]:
    """The fiber a path from ``site`` to one of ``peers`` could run over inside the bound.

    :func:`admissible_fiber` asks the same arithmetic of every site and every peer at once,
    so it keeps a segment that suits any pair anywhere on the map. Here the pair is known,
    and the sharper answer is what a single requirement is written over: without it the
    program can meet a requirement with a way round that runs further than the tenant's
    backup path multiple allows, which :func:`synthesizer.ceiling.independent_paths` then
    refuses to count, and the site reads short over the fiber that was bought for it
    (GitHub issue #113).

    With no bound in hand every segment will do, which is every caller with no tenant to be
    measured against.
    """
    if inputs.limit is None:
        return frozenset(fiber)
    slack = _slack_from(site, inputs, inputs.limit, peers)
    return frozenset(
        segment for segment, length in fiber.items() if _reaches(segment, length, slack)
    )


def _fiber_by_carrier(
    inputs: FiberInputs, fiber: Mapping[tuple[str, str], float]
) -> dict[str, frozenset[tuple[str, str]]]:
    """Each carrier's own share of the fiber, with the fiber nobody owns in every share.

    An operator orders a path from one company end to end, so what a requirement may be met
    over is one carrier's segments plus the segments no carrier owns -- the local fiber the
    operator lays themselves, which every company's path may run along.

    Fiber naming no carrier at all is one share under the empty name, holding the whole of
    it. That is every fixture and every caller with no merged carriers behind it, and it
    leaves the program exactly the one it wrote before carriers were split out.
    """
    if not inputs.fiber_by_carrier:
        return {"": frozenset(fiber)}
    return {
        carrier: frozenset(
            segment
            for segment in fiber
            if not inputs.fiber_segments[segment].carriers
            or carrier in inputs.fiber_segments[segment].carriers
        )
        for carrier in inputs.fiber_by_carrier
    }


def _carried(requirement: _Requirement, whole: Mapping[tuple[str, str], float]) -> int:
    """The most of a requirement this fiber could ever meet, at most what it asks for.

    A site behind a single point of failure on one carrier's fiber cannot be given two ways
    out over it by any amount of buying, so asking for two would leave the program with no
    answer at all rather than with the honest one. What comes back is the largest number
    the fiber survives every separation of, found by asking for one fewer until it does,
    and the shortfall is then reported by
    ``synthesizer.validation.backbone_mesh_independence_deficient`` rather than hidden.
    """
    required = requirement.required
    while required > 0 and weakest_separation(_question(requirement, whole), required):
        required -= 1
    return required


def _shared_out(owed: int, capacity: Mapping[str, int]) -> dict[str, int]:
    """How many ways each carrier is asked for, the company that can carry most asked first.

    A path is bought from one company end to end, so a tenant's number is met a carrier at
    a time and has to be spread over the carriers that can reach the site. The ablest is
    asked first and the rest take what is left, so the fewest companies are involved: an
    operator holding two paths from one carrier and none from a third has one contract
    fewer for the same protection.

    A carrier asked for nothing keeps its entry at nothing, and its caller drops the row --
    a requirement of nothing is met by no fiber at all and would put a column in the
    program for every segment that company owns.
    """
    shares: dict[str, int] = {}
    left = owed
    for carrier, able in sorted(capacity.items(), key=lambda entry: (-entry[1], entry[0])):
        shares[carrier] = min(able, left)
        left -= shares[carrier]
    return shares


def _rows_for(
    site: str,
    peers: frozenset[str],
    spared: frozenset[str],
    writing: _Writing,
    capacity: Mapping[str, int],
) -> list[_Requirement]:
    """One requirement per carrier, each over the fiber that company could sell this site.

    The number asked of each is its share of the tenant's own (see :func:`_shared_out`),
    lowered again to what that company's fiber can actually carry (see :func:`_carried`),
    and a carrier left asking for nothing writes no row.
    """
    budgeted = _within_budget(writing.inputs, writing.fiber, site, peers)
    asked = [
        _Requirement(site, peers, spared, share, writing.by_carrier[carrier] & budgeted)
        for carrier, share in _shared_out(writing.inputs.ways_out, capacity).items()
        if share
    ]
    lowered = [replace(row, required=_carried(row, writing.whole)) for row in asked]
    return [row for row in lowered if row.required]


def _ways_out_rows(site: str, writing: _Writing) -> list[_Requirement]:
    """What one site is owed: as many ways out as the tenant asked, ending at its peers.

    Spread over the carriers by how many of the site's ways out each of them supplies,
    which :func:`synthesizer.ceiling.ways_out_by_carrier` reads off the same proof
    :func:`synthesizer.stages.finalize` later holds the site to. One rule, so the fiber
    bought for a site and the number it is then credited with cannot disagree.
    """
    inputs = writing.inputs
    peers = frozenset(inputs.backbone_ids) - {site}
    spared = frozenset({site}) if writing.per_peer == 1 else frozenset({site}) | peers
    return _rows_for(site, peers, spared, writing, ways_out_by_carrier(site, writing.proof))


def _between_rows(root: str, peer: str, writing: _Writing) -> list[_Requirement]:
    """What one pair is owed: as many paths between them as share no city on the way.

    Every backbone node is spared here and not only the two ends, which is what makes this
    element connectivity -- the requirement the fewest-mile bound is proved for. It is
    written from one site to each of the others rather than between every pair: what it
    takes to separate two sites is never less than the smaller of what it takes to separate
    each of them from a third, so holding one site to every peer holds every pair.

    A ceiling counts a site's ways out to distinct peers, which is not what it takes to
    separate one named pair, so the spread here is by what each carrier's own fiber can
    carry between these two rather than by that count.
    """
    peers = frozenset({peer})
    spared = frozenset(writing.inputs.backbone_ids)
    budgeted = _within_budget(writing.inputs, writing.fiber, root, peers)
    capacity = {
        carrier: _carried(
            _Requirement(
                root, peers, spared, writing.inputs.ways_out, segments & budgeted
            ),
            writing.whole,
        )
        for carrier, segments in writing.by_carrier.items()
    }
    return _rows_for(root, peers, spared, writing, capacity)


def _writing(
    inputs: FiberInputs, fiber: Mapping[tuple[str, str], float]
) -> _Writing:
    """What every requirement over this fiber is written against, worked out once.

    The carrier split, the fiber held outright that a requirement is lowered against, how
    many of a site's ways out one peer may take, and the proof
    :func:`synthesizer.ceiling.ways_out_by_carrier` is asked with. All of them are the same
    for every row, and the proof in particular is one max flow per site per carrier.
    """
    return _Writing(
        inputs,
        fiber,
        _fiber_by_carrier(inputs, fiber),
        {segment: 1.0 for segment in fiber},
        paths_per_peer(inputs.seat_cap, len(inputs.backbone_ids), inputs.ways_out),
        PathProofInputs(
            inputs.backbone_ids,
            build_adjacency(dict(inputs.fiber_segments)),
            inputs.limit,
            inputs.ways_out,
            inputs.seat_cap,
            inputs.fiber_by_carrier,
        ),
    )


def _requirements(
    inputs: FiberInputs, fiber: Mapping[tuple[str, str], float]
) -> list[_Requirement]:
    """Everything the fiber has to do, each row one company's to answer.

    One requirement per site for the ways out it is owed and one per peer of the
    best-served site for the paths between them, and each of those written once per carrier
    that can carry part of it. The site the pairwise requirements are written from is the
    one the carrier's fiber serves best, since holding every pair to what the weakest site
    can manage would spend the whole backbone's protection on one node's shortfall.
    """
    writing = _writing(inputs, fiber)
    ways_out = {site: _ways_out_rows(site, writing) for site in inputs.backbone_ids}
    if not ways_out:
        return []
    root = min(
        ways_out.items(),
        key=lambda owed: (-sum(row.required for row in owed[1]), owed[0]),
    )[0]
    return [row for rows in ways_out.values() for row in rows] + [
        row
        for peer in sorted(set(inputs.backbone_ids) - {root})
        for row in _between_rows(root, peer, writing)
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


def _write(search: _Search, rows: list[SegmentRow]) -> bool:
    """Write down every one of these rows the program is not already holding.

    Whether anything was written is what tells a pass it has learned something. The same
    separation is found from one answer after another -- 92 of the 134 rows this repository's
    many-pass fixture finds are ones it has already written, and Minuteman's national search
    writes 6,376 rows of which 1,740 are distinct -- and a row the program already holds
    constrains it no further while costing a solve and a search on every later pass.
    """
    fresh = []
    for row in rows:
        already = (row.columns, row.floor)
        if already not in search.written:
            search.written.add(already)
            fresh.append(row)
    search.program.add_rows(tuple(fresh))
    return bool(fresh)


def _solve_search(search: _Search, fix: bool) -> SegmentChoice:
    """Solve the program as it stands, with what has been bought held outright or not.

    Holding the bought segments outright is what the rounding needs: each round asks what
    the fewest miles are given the choices already made. Letting them go is what the
    published floor needs, since a floor under the whole problem may take nothing about
    this particular search for granted.
    """
    if fix:
        search.program.hold_whole(
            frozenset(search.column[segment] for segment in search.bought)
        )
    else:
        search.program.hold_nothing()
    return search.program.solve()


def _tighten(search: _Search, requirements: list[_Requirement]) -> SegmentChoice:
    """Solve, look for a requirement the answer misses, write it down, and solve again.

    There is one requirement for every way of separating a site from its peers, far too
    many to write out, so they are written down as an answer violates them: solve with the
    rows so far, search each requirement over the shares that came back, add what that
    found, and solve again. It ends when the answer meets every requirement there is and
    not only the ones on paper, which is what its caller then buys fiber on the strength of.

    Stopping anywhere short of that buys fiber to meet requirements the answer was never
    held to. A cap of 24 passes used to stand here, and every one of the six tenants
    declared then needed hundreds -- 645 for DAF, 1,382 for AFGSC, which ``etc/`` no longer
    declares -- so 36 of Two-Node's 37 rounds spent the cap and rounded an answer that still
    missed three requirements, leaving it holding 17 fiber segments and 871.542 miles more
    than a synthesis meeting the same requirements needs (GitHub issue #63).

    The search ends of its own accord in two ways and both are needed. A pass that finds no
    shortfall has met everything. A pass that finds only separations already written down
    has nothing left to tell the program, so solving again would return the same answer for
    ever; there are finitely many rows and every other pass writes one, so this terminates.
    """
    choice = _solve_search(search, fix=True)
    shortfalls = _shortfalls(requirements, _shares(choice, search.order))
    while shortfalls and _write(search, _rows(shortfalls, search.column)):
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
    """The fiber to build this backbone from, and the fewest miles any synthesis could run.

    Rounds of buying, each one a fewest-miles answer over every requirement written down so
    far with the earlier rounds' segments held outright, until the fiber bought meets every
    requirement on its own. Then one last answer with nothing held outright, which is the
    floor: no synthesis meeting these requirements runs fewer miles than that.

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
        GrowingSegmentProgram(tuple(fiber[segment] for segment in order)),
        set(),
        frozenset(),
    )
    while True:
        shortfalls = _shortfalls(requirements, _held(fiber, search.bought))
        if not shortfalls:
            break
        _write(search, _rows(shortfalls, search.column))
        search.bought |= _round_up(search, _tighten(search, requirements))
    return FiberChoice(search.bought, _solve_search(search, fix=False).miles)
