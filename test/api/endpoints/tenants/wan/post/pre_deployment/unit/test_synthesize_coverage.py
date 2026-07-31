"""Unit tests for which candidate the coverage growth step seats.

These cover ``best_coverage_candidate`` and ``candidate_mesh_ceiling`` in
:mod:`synthesizer.synthesize`, and sit apart from ``test_synthesize.py`` only because that
file reached the thousand-line limit static analysis holds it to. The unit they cover is the
same one, so the split is by file name rather than by unit, which is second best: the fix is
to split the source unit, and what stands in the way of that is recorded in the issue tracker.
"""

from __future__ import annotations

import fixtures
from synthesizer.graphs import build_adjacency
from synthesizer.synthesize import best_coverage_candidate, candidate_mesh_ceiling

physical = fixtures.physical_edges_from

# Fiber where spans and independent routes disagree. Three base nodes sit in a triangle.
# "rich" and "rich_far" reach all three directly, so each holds three links that fail
# independently. "poor" and "poor_far" reach two directly and spend their third span on a
# stub that rejoins the backbone at b1, so that third route can only re-cross a city they
# already depend on and each holds two. Three spans apiece either way, which is the number a
# raw span count would rank them by and the reason it is the wrong number to rank them by.
_FIBER_EDGES = physical({
    ("b1", "b2"): 1.0, ("b2", "b3"): 1.0, ("b1", "b3"): 1.0,
    ("poor", "x"): 1.0, ("x", "b1"): 1.0, ("poor_far", "x2"): 1.0, ("x2", "b1"): 1.0,
    **{(name, base): 1.0 for name in ("rich", "rich_far") for base in ("b1", "b2", "b3")},
    **{(name, base): 1.0 for name in ("poor", "poor_far") for base in ("b1", "b2")},
})
_FIBER_ADJACENCY = build_adjacency(_FIBER_EDGES)
_FIBER_BACKBONE = ("b1", "b2", "b3")
# Both bring the worst haul inside the fifty-mile target and the worse-connected one is
# nearer, so distance and fiber name different winners. In the second pair neither reaches
# the target, and again the worse-connected one is nearer.
_BOTH_COVER = [(0.0, "poor"), (6.9, "rich")]
_NEITHER_COVERS = [(103.6, "poor_far"), (138.2, "rich_far")]


def _seated(improving: list[tuple[float, str]]) -> str:
    """Which of these candidates the growth step seats over the fiber above, at 50 miles."""
    return best_coverage_candidate(improving, _FIBER_BACKBONE, _FIBER_ADJACENCY, 50.0)


def test_the_better_connected_of_two_covering_candidates_is_seated() -> None:
    """Coverage is answered by both, so the one whose fiber carries more links wins."""
    assert _seated(_BOTH_COVER) == "rich"


def test_a_candidates_spans_are_not_counted_as_independent_routes() -> None:
    """Three spans leave poor, and two independent routes out are all its own fiber allows."""
    assert candidate_mesh_ceiling("poor", _FIBER_BACKBONE, _FIBER_ADJACENCY) == 2


def test_the_nearest_candidate_is_seated_when_none_satisfies_the_target() -> None:
    """No candidate answers the round, so the gap is closed as far as it can be instead."""
    assert _seated(_NEITHER_COVERS) == "poor_far"
