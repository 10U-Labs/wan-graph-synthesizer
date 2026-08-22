from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

from synthesizer.input_graph import link_key

_Half = tuple[str, str]
_Residual = dict[_Half, dict[_Half, float]]

_SINK: _Half = ("sink", "")

_TOLERANCE = 1e-6


@dataclass(frozen=True)
class SeparationQuestion:
    site: str
    peers: frozenset[str]
    spared: frozenset[str]
    held: Mapping[tuple[str, str], float]


@dataclass(frozen=True)
class Separation:
    lost_cities: frozenset[str]
    crossing_segments: frozenset[tuple[str, str]]


def _half(city: str, side: str, spared: frozenset[str]) -> _Half:
    return ("out", city) if city in spared else (side, city)


def _add_arc(residual: _Residual, tail: _Half, head: _Half, capacity: float) -> None:
    arcs = residual.setdefault(tail, {})
    arcs[head] = arcs.get(head, 0.0) + capacity
    residual.setdefault(head, {}).setdefault(tail, 0.0)


def _residual_network(question: SeparationQuestion) -> _Residual:
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
