from __future__ import annotations

import pytest

from synthesizer import linear_program
from synthesizer.linear_program import (
    GrowingSegmentProgram,
    SegmentProgram,
    SegmentRow,
    solve,
)

_TWO_COLUMNS = (10.0, 1.0)
_LONG = 0
_SHORT = 1


def _answer(
    rows: tuple[SegmentRow, ...], selected: frozenset[int] = frozenset()
) -> tuple[float, ...]:
    choice = solve(SegmentProgram(_TWO_COLUMNS, selected, rows))
    return (choice.miles, *choice.held)


def test_a_program_that_asks_for_nothing_holds_nothing_and_runs_no_miles() -> None:
    assert _answer(()) == pytest.approx((0.0, 0.0, 0.0))


def test_a_row_either_column_could_meet_is_met_by_the_shorter_one() -> None:
    assert _answer((SegmentRow((_LONG, _SHORT), 1.0),)) == pytest.approx((1.0, 0.0, 1.0))


def test_a_column_already_selected_is_held_whole_and_its_miles_are_counted() -> None:
    assert _answer((), frozenset({_LONG})) == pytest.approx((10.0, 1.0, 0.0))


def test_a_row_asking_for_two_over_two_columns_holds_both_of_them() -> None:
    assert _answer((SegmentRow((_LONG, _SHORT), 2.0),)) == pytest.approx((11.0, 1.0, 1.0))


def test_a_floor_no_amount_of_fiber_could_reach_is_raised_by_name() -> None:
    with pytest.raises(ValueError, match="capped against the fiber"):
        _answer((SegmentRow((_LONG, _SHORT), 3.0),))


_SPREAD = SegmentRow((_LONG, _SHORT), 1.0)
_ALL_OF_SHORT = SegmentRow((_SHORT,), 1.0)
_HALF_OF_LONG = SegmentRow((_LONG,), 0.5)
_EVERY_ROW = (_SPREAD, _ALL_OF_SHORT, _HALF_OF_LONG)


def test_rows_written_a_batch_at_a_time_answer_as_the_same_rows_written_at_once() -> None:
    growing = GrowingSegmentProgram(_TWO_COLUMNS)
    growing.add_rows((_SPREAD,))
    growing.solve()
    growing.add_rows((_ALL_OF_SHORT, _HALF_OF_LONG))
    batched = growing.solve()
    assert (batched.miles, *batched.held) == pytest.approx(_answer(_EVERY_ROW))


def test_a_column_let_go_of_is_no_longer_held_whole_and_the_answer_comes_back_down() -> None:
    growing = GrowingSegmentProgram(_TWO_COLUMNS)
    growing.add_rows(_EVERY_ROW)
    growing.hold_whole(frozenset({_LONG}))
    growing.solve()
    growing.hold_nothing()
    assert growing.solve().miles == pytest.approx(6.0)


def test_writing_no_rows_at_all_leaves_the_program_answering_as_it_did() -> None:
    growing = GrowingSegmentProgram(_TWO_COLUMNS)
    growing.add_rows(_EVERY_ROW)
    growing.add_rows(())
    assert growing.solve().miles == pytest.approx(6.0)


def _out_of_time_at_once(monkeypatch: pytest.MonkeyPatch) -> GrowingSegmentProgram:
    monkeypatch.setattr(linear_program, "_SECONDS_A_PASS_MAY_RUN", 0.0)
    growing = GrowingSegmentProgram(_TWO_COLUMNS)
    growing.add_rows(_EVERY_ROW)
    return growing


def test_a_pass_that_gives_up_is_asked_again_and_comes_back_with_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _out_of_time_at_once(monkeypatch).solve().miles == pytest.approx(6.0)


def test_a_pass_that_gives_up_holds_the_same_fiber_a_pass_that_did_not_would(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _out_of_time_at_once(monkeypatch).solve().held == pytest.approx((0.5, 1.0))
