from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import TypeVar

from synthesizer.ceiling import (
    BackupPathLimit,
    PathProofInputs,
    paths_per_peer,
    ways_out_by_carrier_and_peer,
)
from synthesizer.flow_cuts import Separation, SeparationQuestion, weakest_separation
from synthesizer.graphs import build_adjacency
from synthesizer.input_graph import FiberSegment
from synthesizer.linear_program import GrowingSegmentProgram, SegmentChoice, SegmentRow

_HELD_OUTRIGHT = 0.5

_TOLERANCE = 1e-6

_Bucket = TypeVar("_Bucket", str, tuple[str, str])


@dataclass(frozen=True)
class FiberInputs:
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
    segments: frozenset[tuple[str, str]]
    lower_bound_miles: float


@dataclass(frozen=True)
class _Requirement:
    site: str
    peers: frozenset[str]
    spared: frozenset[str]
    required: int
    over: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class _Writing:
    inputs: FiberInputs
    fiber: Mapping[tuple[str, str], float]
    by_carrier: Mapping[str, frozenset[tuple[str, str]]]
    whole: Mapping[tuple[str, str], float]
    per_peer: int
    proof: PathProofInputs


@dataclass(frozen=True)
class _Asked:
    site: str
    peers: frozenset[str]
    spared: frozenset[str]
    over: Mapping[str, frozenset[tuple[str, str]]]
    capacity: Mapping[str, int]


@dataclass(frozen=True)
class _WaysOut:
    toward_each: list[_Requirement]
    together: list[_Requirement]


@dataclass(frozen=True)
class _BudgetSlack:
    reach: Mapping[str, float]
    spare: Mapping[str, float]


@dataclass
class _Search:
    order: list[tuple[str, str]]
    column: dict[tuple[str, str], int]
    program: GrowingSegmentProgram
    written: set[tuple[tuple[int, ...], float]]
    selected: frozenset[tuple[str, str]]


def _slack_from(
    site: str, inputs: FiberInputs, limit: BackupPathLimit, peers: Iterable[str]
) -> _BudgetSlack:
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
    left, right = segment
    return any(
        slack.reach.get(near, math.inf) + length + slack.spare.get(far, math.inf) <= _TOLERANCE
        for near, far in ((left, right), (right, left))
    )


def admissible_fiber(inputs: FiberInputs) -> dict[tuple[str, str], float]:
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
    if inputs.limit is None:
        return frozenset(fiber)
    slack = _slack_from(site, inputs, inputs.limit, peers)
    return frozenset(
        segment for segment, length in fiber.items() if _reaches(segment, length, slack)
    )


def _fiber_by_carrier(
    inputs: FiberInputs, fiber: Mapping[tuple[str, str], float]
) -> dict[str, frozenset[tuple[str, str]]]:
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


def _question(
    requirement: _Requirement, held: Mapping[tuple[str, str], float]
) -> SeparationQuestion:
    return SeparationQuestion(
        requirement.site,
        requirement.peers,
        requirement.spared,
        {segment: share for segment, share in held.items() if segment in requirement.over},
    )


def _carried(requirement: _Requirement, whole: Mapping[tuple[str, str], float]) -> int:
    required = requirement.required
    while required > 0 and weakest_separation(_question(requirement, whole), required):
        required -= 1
    return required


def _shared_out(owed: int, capacity: Mapping[_Bucket, int]) -> dict[_Bucket, int]:
    shares: dict[_Bucket, int] = {}
    left = owed
    for bucket, able in sorted(capacity.items(), key=lambda entry: (-entry[1], entry[0])):
        shares[bucket] = min(able, left)
        left -= shares[bucket]
    return shares


def _lowered(
    rows: list[_Requirement], whole: Mapping[tuple[str, str], float]
) -> list[_Requirement]:
    carried = [replace(row, required=_carried(row, whole)) for row in rows]
    return [row for row in carried if row.required]


def _rows_for(asked: _Asked, writing: _Writing) -> list[_Requirement]:
    return _lowered(
        [
            _Requirement(asked.site, asked.peers, asked.spared, share, asked.over[carrier])
            for carrier, share in _shared_out(
                writing.inputs.ways_out, asked.capacity
            ).items()
            if share
        ],
        writing.whole,
    )


def _peer_fiber(
    site: str, writing: _Writing, capacity: Mapping[tuple[str, str], int]
) -> dict[tuple[str, str], frozenset[tuple[str, str]]]:
    return {
        (carrier, peer): writing.by_carrier[carrier]
        & _within_budget(writing.inputs, writing.fiber, site, frozenset({peer}))
        for carrier, peer in capacity
    }


def _asked_of_all_peers(
    site: str,
    spared: frozenset[str],
    capacity: Mapping[tuple[str, str], int],
    peer_fiber: Mapping[tuple[str, str], frozenset[tuple[str, str]]],
) -> _Asked:
    able: dict[str, int] = {}
    reach: dict[str, frozenset[tuple[str, str]]] = {}
    for (carrier, peer), proved in capacity.items():
        able[carrier] = able.get(carrier, 0) + proved
        reach[carrier] = reach.get(carrier, frozenset()) | peer_fiber[(carrier, peer)]
    peers = frozenset(peer for _carrier, peer in capacity)
    return _Asked(site, peers, spared, reach, able)


def _ways_out_rows(site: str, writing: _Writing) -> _WaysOut:
    peers = frozenset(writing.inputs.backbone_ids) - {site}
    spared = frozenset({site}) if writing.per_peer == 1 else frozenset({site}) | peers
    capacity = ways_out_by_carrier_and_peer(site, writing.proof)
    peer_fiber = _peer_fiber(site, writing, capacity)
    toward_each = _lowered(
        [
            _Requirement(
                site, frozenset({peer}), spared, share, peer_fiber[(carrier, peer)]
            )
            for (carrier, peer), share in _shared_out(
                writing.inputs.ways_out, capacity
            ).items()
            if share
        ],
        writing.whole,
    )
    return _WaysOut(
        toward_each,
        _rows_for(_asked_of_all_peers(site, spared, capacity, peer_fiber), writing),
    )


def _between_rows(root: str, peer: str, writing: _Writing) -> list[_Requirement]:
    asking = frozenset({peer})
    spared = frozenset(writing.inputs.backbone_ids)
    capacity = {
        carrier: _carried(
            _Requirement(root, asking, spared, writing.inputs.ways_out, segments),
            writing.whole,
        )
        for carrier, segments in writing.by_carrier.items()
    }
    return _rows_for(
        _Asked(root, asking, spared, writing.by_carrier, capacity), writing
    )


def _writing(
    inputs: FiberInputs, fiber: Mapping[tuple[str, str], float]
) -> _Writing:
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
    writing = _writing(inputs, fiber)
    ways_out = {site: _ways_out_rows(site, writing) for site in inputs.backbone_ids}
    if not ways_out:
        return []
    root = min(
        ways_out.items(),
        key=lambda owed: (-sum(row.required for row in owed[1].together), owed[0]),
    )[0]
    return [
        row for rows in ways_out.values() for row in rows.toward_each + rows.together
    ] + [
        row
        for peer in sorted(set(inputs.backbone_ids) - {root})
        for row in _between_rows(root, peer, writing)
    ]


def _shortfalls(
    requirements: list[_Requirement], held: Mapping[tuple[str, str], float]
) -> list[tuple[Separation, int]]:
    found: list[tuple[Separation, int]] = []
    for requirement in requirements:
        separation = weakest_separation(_question(requirement, held), requirement.required)
        if separation is not None:
            found.append((separation, requirement.required))
    return found


def _rows(
    shortfalls: list[tuple[Separation, int]], column: Mapping[tuple[str, str], int]
) -> list[SegmentRow]:
    return [
        SegmentRow(
            tuple(sorted(column[segment] for segment in separation.crossing_segments)),
            float(required - len(separation.lost_cities)),
        )
        for separation, required in shortfalls
    ]


def _held(
    fiber: Mapping[tuple[str, str], float], selected: frozenset[tuple[str, str]]
) -> dict[tuple[str, str], float]:
    return {segment: 1.0 if segment in selected else 0.0 for segment in fiber}


def _shares(
    choice: SegmentChoice, order: list[tuple[str, str]]
) -> dict[tuple[str, str], float]:
    return dict(zip(order, choice.held))


def _write(search: _Search, rows: list[SegmentRow]) -> bool:
    fresh = []
    for row in rows:
        already = (row.columns, row.floor)
        if already not in search.written:
            search.written.add(already)
            fresh.append(row)
    search.program.add_rows(tuple(fresh))
    return bool(fresh)


def _solve_search(search: _Search, fix: bool) -> SegmentChoice:
    if fix:
        search.program.hold_whole(
            frozenset(search.column[segment] for segment in search.selected)
        )
    else:
        search.program.hold_nothing()
    return search.program.solve()


def _tighten(search: _Search, requirements: list[_Requirement]) -> SegmentChoice:
    choice = _solve_search(search, fix=True)
    shortfalls = _shortfalls(requirements, _shares(choice, search.order))
    while shortfalls and _write(search, _rows(shortfalls, search.column)):
        choice = _solve_search(search, fix=True)
        shortfalls = _shortfalls(requirements, _shares(choice, search.order))
    return choice


def _round_up(search: _Search, choice: SegmentChoice) -> frozenset[tuple[str, str]]:
    shares = _shares(choice, search.order)
    left = [
        (share, segment) for segment, share in shares.items() if segment not in search.selected
    ]
    fresh = frozenset(
        segment for share, segment in left if share >= _HELD_OUTRIGHT - _TOLERANCE
    )
    return fresh or frozenset({max(left)[1]})


def choose_fiber(inputs: FiberInputs) -> FiberChoice:
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
        shortfalls = _shortfalls(requirements, _held(fiber, search.selected))
        if not shortfalls:
            break
        _write(search, _rows(shortfalls, search.column))
        search.selected |= _round_up(search, _tighten(search, requirements))
    return FiberChoice(search.selected, _solve_search(search, fix=False).miles)
