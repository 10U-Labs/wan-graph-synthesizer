"""How much has to be lost before a backbone node is cut off from the peers it must reach.

A backbone owes each of its nodes a number of ways out and each pair of them a number of
ways between, and both are one question asked of a set of fiber segments: how many cities
and how much fiber have to fail together before the two sides come apart. This module
answers that question over segments held in whatever fraction they have been bought so
far, and where the answer falls short it hands back the separation itself -- the cities
that fail and the segments that cross it. That separation is the requirement the fiber in
hand does not meet, written in the one form a buyer can act on: buy more of these
segments.

Cities fail and the two ends of a path do not. A path is taken down by every city it
crosses, so a city is worth one unit of separation. The site being measured and any site
named in ``spared`` are the ends the paths run between, and losing one of those loses the
destination rather than the protection between here and there -- which is the same
distinction :func:`synthesizer.validation.diverse_path_count` draws when it counts a
site's ways out.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

from synthesizer.input_graph import link_key

# One side of a city a path may cross only once: the fiber arriving is ("in", city), the
# fiber leaving is ("out", city), and one unit of capacity joins them. A city that cannot
# fail is held as ("out", city) alone, so there is nothing between its two sides to lose.
_Half = tuple[str, str]
_Residual = dict[_Half, dict[_Half, float]]

_SINK: _Half = ("sink", "")

# Slack in units of held segment, absorbing the arithmetic of a solved linear program. A
# millionth of a segment, far too little to admit any fiber a real requirement turns on.
_TOLERANCE = 1e-6


@dataclass(frozen=True)
class SeparationQuestion:
    """What is being asked of a set of fiber segments, and on whose behalf.

    ``site`` is the backbone node the ways out are counted from and ``peers`` are the
    places one of those ways may end. ``spared`` are the cities that cannot fail: always
    the site itself, and the peers as well wherever a peer is a destination rather than a
    city a path passes through. ``held`` is how much of each candidate segment has been
    bought, from none of it to all of it; a segment held at none of it still appears,
    because a separation it crosses is a separation buying it would close.
    """

    site: str
    peers: frozenset[str]
    spared: frozenset[str]
    held: Mapping[tuple[str, str], float]


@dataclass(frozen=True)
class Separation:
    """One way to cut a site off from its peers: the cities that fail, the fiber that crosses.

    The fiber meets the requirement behind this separation when the segments crossing it
    are held to at least the number of ways asked for, less one for each city lost --
    losing a city costs as much as losing every segment a path through it would have used.
    """

    lost_cities: frozenset[str]
    crossing_segments: frozenset[tuple[str, str]]


def _half(city: str, side: str, spared: frozenset[str]) -> _Half:
    """Which end of a city fiber attaches to, held as one end where the city cannot fail."""
    return ("out", city) if city in spared else (side, city)


def _add_arc(residual: _Residual, tail: _Half, head: _Half, capacity: float) -> None:
    """Add capacity one way and seed the arc that gives it back.

    The reverse arc starts empty so an augmenting walk can undo an earlier choice, which is
    what lets a sequence of greedy walks end at a largest flow rather than at a dead end.
    """
    arcs = residual.setdefault(tail, {})
    arcs[head] = arcs.get(head, 0.0) + capacity
    residual.setdefault(head, {}).setdefault(tail, 0.0)


def _residual_network(question: SeparationQuestion) -> _Residual:
    """The network whose largest flow out of ``site`` is the ways out the fiber carries.

    Every city that can fail is split around a single unit, so no two ways out cross it;
    every candidate segment becomes capacity in both directions, as much of it as is held;
    and every peer feeds the sink without limit, since a peer is where a way out ends
    rather than something the count is rationed by.
    """
    spared = question.spared | {question.site}
    residual: _Residual = {}
    cities = {city for segment in question.held for city in segment}
    for city in sorted(cities - spared):
        _add_arc(residual, ("in", city), ("out", city), 1.0)
    for (left, right), share in question.held.items():
        _add_arc(residual, ("out", left), _half(right, "in", spared), share)
        _add_arc(residual, ("out", right), _half(left, "in", spared), share)
    for peer in sorted(question.peers & cities):
        _add_arc(residual, ("out", peer), _SINK, math.inf)
    return residual


def _walk(residual: _Residual, source: _Half) -> dict[_Half, _Half]:
    """Every half a walk of unspent capacity reaches from ``source``, and how it got there.

    Fewest hops first, which is what bounds how many walks a largest flow takes. The map is
    read two ways: while capacity still reaches the sink it is the next walk to send flow
    down, and once it does not it is the separation itself -- the halves on this side of it.
    """
    reached: dict[_Half, _Half] = {source: source}
    queue: deque[_Half] = deque([source])
    while queue:
        tail = queue.popleft()
        for head, capacity in residual.get(tail, {}).items():
            if capacity > _TOLERANCE and head not in reached:
                reached[head] = tail
                queue.append(head)
    return reached


def _send(residual: _Residual, reached: dict[_Half, _Half], source: _Half) -> float:
    """Send as much down the walk to the sink as its narrowest arc allows."""
    steps: list[tuple[_Half, _Half]] = []
    head = _SINK
    while head != source:
        tail = reached[head]
        steps.append((tail, head))
        head = tail
    carried = min(residual[tail][head] for tail, head in steps)
    for tail, head in steps:
        residual[tail][head] -= carried
        residual[head][tail] += carried
    return carried


def _read_separation(question: SeparationQuestion, reached: dict[_Half, _Half]) -> Separation:
    """Read the separation off the halves a finished flow can still reach.

    A city the walk enters and cannot leave is a city the flow is using to its limit, so it
    is one of the cities that fail. Everything the walk leaves is on this side of the
    separation, and a candidate segment with one end on each side is fiber that crosses it
    -- whether or not any of that segment has been bought, since buying it is the repair.
    """
    spared = question.spared | {question.site}
    lost = frozenset(
        city
        for side, city in reached
        if side == "in" and city not in spared and ("out", city) not in reached
    )
    near = {city for side, city in reached if side == "out"}
    crossing = frozenset(
        link_key(left, right)
        for left, right in question.held
        if (left in near) != (right in near) and left not in lost and right not in lost
    )
    return Separation(lost, crossing)


def weakest_separation(question: SeparationQuestion, required: int) -> Separation | None:
    """The separation the fiber is least able to survive, or None when it carries enough.

    Ways out are counted by sending one at a time down whatever unspent capacity is left,
    stopping the moment ``required`` of them are in hand: what is being asked is whether
    the fiber carries that many, not how many more it could carry, and the surplus costs
    walks to find and answers nothing.

    Where it cannot, the walks run out and what is left is the separation -- by the
    max-flow min-cut theorem the very cities and segments whose loss the fiber cannot
    survive, and the smallest such set there is.
    """
    residual = _residual_network(question)
    source: _Half = ("out", question.site)
    carried = 0.0
    reached = _walk(residual, source)
    while carried + _TOLERANCE < required and _SINK in reached:
        carried += _send(residual, reached, source)
        reached = _walk(residual, source)
    if carried + _TOLERANCE >= required:
        return None
    return _read_separation(question, reached)
