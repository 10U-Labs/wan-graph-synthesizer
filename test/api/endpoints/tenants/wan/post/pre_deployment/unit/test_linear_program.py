"""Unit tests for buying the fewest miles of fiber that meet a list of floors.

Nothing about backbones, tenants or maps crosses into this module, so nothing about them
crosses into its tests either: what is handed over is a column per fiber segment with a
mileage on it, and rows saying that some group of columns must hold at least so much
between them. Two columns are enough to tell every answer here apart. One runs ten miles
and one runs one, so a row either of them could meet is met by the short one wherever the
answer is the fewest miles, and there is never a tie for a solver to break.

The one program with no answer is the same two columns under a floor of three. Nothing is
bought twice, so two whole segments hold two, and a row asking for more than that is a row
no design could ever meet -- which the module raises by name rather than returning, because
a design built on a silent zero would be fiber nobody can order.
"""

from __future__ import annotations

import pytest

from synthesizer.linear_program import SegmentProgram, SegmentRow, solve

# The two columns every program below is written over: ten miles and one mile.
_TWO_COLUMNS = (10.0, 1.0)
_LONG = 0
_SHORT = 1


def _answer(
    rows: tuple[SegmentRow, ...], bought: frozenset[int] = frozenset()
) -> tuple[float, ...]:
    """The fewest miles the rows allow, then how much of each column that answer holds."""
    choice = solve(SegmentProgram(_TWO_COLUMNS, bought, rows))
    return (choice.miles, *choice.held)


def test_a_program_that_asks_for_nothing_holds_nothing_and_runs_no_miles() -> None:
    """Two segments on offer and no row asking for either, so the answer buys neither.

    It is the shape the published floor is computed in when a backbone asks nothing of the
    fiber in front of it, and it has to come back at zero rather than at what the columns
    would have cost had anything wanted them.
    """
    assert _answer(()) == pytest.approx((0.0, 0.0, 0.0))


def test_a_row_either_column_could_meet_is_met_by_the_shorter_one() -> None:
    """One unit asked for over a ten-mile column and a one-mile one: the answer runs one mile.

    This is the whole of what the solver is for. Both columns meet the row on their own, so
    only the mileage separates them, and an answer taking the long one would order ten times
    the fiber for the same requirement.
    """
    assert _answer((SegmentRow((_LONG, _SHORT), 1.0),)) == pytest.approx((1.0, 0.0, 1.0))


def test_a_column_already_bought_is_held_whole_and_its_miles_are_counted() -> None:
    """The ten-mile column is bought and no row wants it, and the answer is ten miles anyway.

    Each round of buying asks what the fewest miles are given the choices already made, so a
    segment an earlier round settled on is held at a whole segment whatever the rows say, and
    the miles it runs belong to the answer the same as any other.
    """
    assert _answer((), frozenset({_LONG})) == pytest.approx((10.0, 1.0, 0.0))


def test_a_row_asking_for_two_over_two_columns_holds_both_of_them() -> None:
    """Two units asked for and two columns to hold them, so both come back at a whole segment.

    A separation crossed by exactly as much fiber as the requirement across it needs leaves
    the answer no choice at all, which is the case a ring arrives as: every segment of it
    bought, and eleven miles between the two here.
    """
    assert _answer((SegmentRow((_LONG, _SHORT), 2.0),)) == pytest.approx((11.0, 1.0, 1.0))


def test_a_floor_no_amount_of_buying_could_reach_is_raised_by_name() -> None:
    """Three units asked for over two columns that hold two between them, so there is no answer.

    Nothing is bought twice, so this is a requirement that was never capped against the fiber
    actually there. It is a defect in whoever wrote the row rather than a finding about the
    fiber, and it is raised where it happens so that the caller reads which requirement it was
    rather than a design that quietly bought nothing.
    """
    with pytest.raises(ValueError, match="capped against the fiber"):
        _answer((SegmentRow((_LONG, _SHORT), 3.0),))
