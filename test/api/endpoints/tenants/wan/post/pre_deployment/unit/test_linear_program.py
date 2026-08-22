"""Unit tests for finding the fewest miles of fiber that meet a list of floors.

Nothing about backbones, tenants or maps crosses into this module, so nothing about them
crosses into its tests either: what is handed over is a column per fiber segment with a
mileage on it, and rows saying that some group of columns must hold at least so much
between them. Two columns are enough to tell every answer here apart. One runs ten miles
and one runs one, so a row either of them could meet is met by the short one wherever the
answer is the fewest miles, and there is never a tie for a solver to break.

The one program with no answer is the same two columns under a floor of three. Nothing is
held twice, so two whole segments hold two, and a row asking for more than that is a row
no synthesis could ever meet -- which the module raises by name rather than returning, because
a synthesis built on a silent zero would be fiber nobody can order.

A program can also be written a few rows at a time, because the search that writes the rows
does not know them when it starts. That is a second way of asking the same question and it
has to come back with the same answer, so one case here asks it both ways and holds the two
together.

The last cases are about a pass that does not answer. A solver carried through hundreds of
passes can start a pass from a basis that has gone bad and then never finish it, which cost
DOW its whole network (GitHub issue #70), so a pass is given up on and asked again with that
basis thrown away. Two columns settle in microseconds however they are asked, so the only
way to reach that from here is to allow a pass no time at all.
"""

from __future__ import annotations

import pytest

from synthesizer import linear_program
from synthesizer.linear_program import (
    GrowingSegmentProgram,
    SegmentProgram,
    SegmentRow,
    solve,
)

# The two columns every program below is written over: ten miles and one mile.
_TWO_COLUMNS = (10.0, 1.0)
_LONG = 0
_SHORT = 1


def _answer(
    rows: tuple[SegmentRow, ...], selected: frozenset[int] = frozenset()
) -> tuple[float, ...]:
    """The fewest miles the rows allow, then how much of each column that answer holds."""
    choice = solve(SegmentProgram(_TWO_COLUMNS, selected, rows))
    return (choice.miles, *choice.held)


def test_a_program_that_asks_for_nothing_holds_nothing_and_runs_no_miles() -> None:
    """Two segments on offer and no row asking for either, so the answer holds neither.

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


def test_a_column_already_selected_is_held_whole_and_its_miles_are_counted() -> None:
    """The ten-mile column is selected and no row wants it, and the answer is ten miles anyway.

    Each round of selecting asks what the fewest miles are given the choices already made, so a
    segment an earlier round settled on is held at a whole segment whatever the rows say, and
    the miles it runs belong to the answer the same as any other.
    """
    assert _answer((), frozenset({_LONG})) == pytest.approx((10.0, 1.0, 0.0))


def test_a_row_asking_for_two_over_two_columns_holds_both_of_them() -> None:
    """Two units asked for and two columns to hold them, so both come back at a whole segment.

    A separation crossed by exactly as much fiber as the requirement across it needs leaves
    the answer no choice at all, which is the case a ring arrives as: every segment of it
    selected, and eleven miles between the two here.
    """
    assert _answer((SegmentRow((_LONG, _SHORT), 2.0),)) == pytest.approx((11.0, 1.0, 1.0))


def test_a_floor_no_amount_of_fiber_could_reach_is_raised_by_name() -> None:
    """Three units asked for over two columns that hold two between them, so there is no answer.

    Nothing is held twice, so this is a requirement that was never capped against the fiber
    actually there. It is a defect in whoever wrote the row rather than a finding about the
    fiber, and it is raised where it happens so that the caller reads which requirement it was
    rather than a synthesis that quietly selected nothing.
    """
    with pytest.raises(ValueError, match="capped against the fiber"):
        _answer((SegmentRow((_LONG, _SHORT), 3.0),))


# The same three rows, which the two cases below put to the solver in one go and in two
# batches: one unit spread over both columns, a whole segment of the short one, and half of
# the long one. The answer is six miles, holding half of the long column and all of the
# short one.
_SPREAD = SegmentRow((_LONG, _SHORT), 1.0)
_ALL_OF_SHORT = SegmentRow((_SHORT,), 1.0)
_HALF_OF_LONG = SegmentRow((_LONG,), 0.5)
_EVERY_ROW = (_SPREAD, _ALL_OF_SHORT, _HALF_OF_LONG)


def test_rows_written_a_batch_at_a_time_answer_as_the_same_rows_written_at_once() -> None:
    """One row, an answer, then two more rows, and the end of it is the whole program's answer.

    This is what lets a whole search run on one solver. The search solves, looks at the
    answer for a requirement it misses, writes that down and solves again, hundreds of times
    over: DAF needed 645 passes and AFGSC, which ``etc/`` no longer declares, 1,382.
    Building a new solver for each of them and re-solving from nothing is where a national
    build spent almost all of its fifteen minutes -- 96.2% of Two-Node's fiber choice and
    91.9% of Minuteman's (GitHub issue #63).

    Carrying one solver through is only safe if it answers what a solver handed the finished
    program answers, and it is asserted rather than assumed because the whole of the fiber
    choice now stands on it. Both the miles and what each column holds are compared, since
    an objective that matches over holdings that do not would select different fiber for the
    same number of miles.
    """
    growing = GrowingSegmentProgram(_TWO_COLUMNS)
    growing.add_rows((_SPREAD,))
    growing.solve()
    growing.add_rows((_ALL_OF_SHORT, _HALF_OF_LONG))
    batched = growing.solve()
    assert (batched.miles, *batched.held) == pytest.approx(_answer(_EVERY_ROW))


def test_a_column_let_go_of_is_no_longer_held_whole_and_the_answer_comes_back_down() -> None:
    """The long column is held whole, then let go, and the answer returns to six miles.

    A round of selecting asks what the fewest miles are given the segments it has already
    settled on, so those are held at a whole segment while it runs. The floor published with
    the finished synthesis may take none of that for granted -- it is the fewest miles any
    synthesis meeting the requirements could run, whatever this particular search happened to
    select -- so every column is let go before it is computed. A column that stayed held would
    put the search's own choices into the number the synthesis is judged against.
    """
    growing = GrowingSegmentProgram(_TWO_COLUMNS)
    growing.add_rows(_EVERY_ROW)
    growing.hold_whole(frozenset({_LONG}))
    growing.solve()
    growing.hold_nothing()
    assert growing.solve().miles == pytest.approx(6.0)


def test_writing_no_rows_at_all_leaves_the_program_answering_as_it_did() -> None:
    """A batch with nothing in it is written, and the answer is the one from before it.

    This is the batch a search writes when every separation it has just found is one it
    wrote down earlier, and reaching it is how the search knows to stop: a program that
    learned nothing will answer the same thing for ever if it is asked again. So the empty
    batch has to be a no-op rather than a call into the solver with no rows in hand.
    """
    growing = GrowingSegmentProgram(_TWO_COLUMNS)
    growing.add_rows(_EVERY_ROW)
    growing.add_rows(())
    assert growing.solve().miles == pytest.approx(6.0)


def _out_of_time_at_once(monkeypatch: pytest.MonkeyPatch) -> GrowingSegmentProgram:
    """The three-row program, on a search that allows a pass no time to answer in.

    An allowance of nothing is the only way to reach the retry from a test. A pass gives up
    when it has run longer than the search allows it, and the two columns here are answered
    in tens of microseconds however the solver goes about it, so no allowance a test could
    write would be reached by the work itself. At nothing, the first attempt is over before
    it starts and every pass takes the path the retry is for.
    """
    monkeypatch.setattr(linear_program, "_SECONDS_A_PASS_MAY_RUN", 0.0)
    growing = GrowingSegmentProgram(_TWO_COLUMNS)
    growing.add_rows(_EVERY_ROW)
    return growing


def test_a_pass_that_gives_up_is_asked_again_and_comes_back_with_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pass that runs out of time still answers six miles, which is the program's answer.

    The whole of a national build turns on this. DOW's fiber search runs 4,478 passes and
    one of them -- the 713th, over 624 segments and 5,879 rows -- never comes back at all:
    the solver has been carried through every pass before it and the basis it starts from
    has gone bad. The program itself is easy, and a solver handed it fresh answers in 0.682
    seconds. So the tenant was recorded as ``fail`` and published no network, on a synthesis
    that is there to be built, for want of asking one question twice (GitHub issue #70).
    """
    assert _out_of_time_at_once(monkeypatch).solve().miles == pytest.approx(6.0)


def test_a_pass_that_gives_up_holds_the_same_fiber_a_pass_that_did_not_would(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Half the long column and all of the short one, which is what the rows ask for.

    The miles are asserted beside this and are not enough on their own, because a retry that
    answered a different question could reach the same total over different segments and hand
    the operator fiber the search never chose. It also says the give-up is not mistaken for
    the one case ``_answer`` raises on: a row nothing could ever meet is a defect in whoever
    wrote it, and a pass that merely wants asking again is not.
    """
    assert _out_of_time_at_once(monkeypatch).solve().held == pytest.approx((0.5, 1.0))
