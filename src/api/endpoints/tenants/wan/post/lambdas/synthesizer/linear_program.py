"""Buy the fewest miles of fiber that meet a list of "hold at least this much" rows.

This is the one place the synthesizer hands a problem to a solver, and it is deliberately
the smallest problem it can hand over: a column for each fiber segment, held anywhere
between none of it and all of it, a mileage on each column, and a list of rows saying that
some group of columns must hold at least so much between them. The answer is the fewest
miles that satisfies every row, and how much of each segment that answer holds.

Nothing about backbones, tenants or maps crosses this line. What a row means -- that some
set of cities and segments would cut a site off from its peers unless enough of that fiber
is bought -- is :mod:`synthesizer.survivable`'s business, and what comes back is a number
per column that module reads as fiber.

The solver is HiGHS, through its Python package ``highspy``: MIT licensed, developed at
the University of Edinburgh, and the same solver ``scipy.optimize.linprog`` calls, reached
here without SciPy's hundred megabytes of compiled code. It ships to the synthesizer
Lambda as a layer rather than inside the function, so no third-party code lands under
``src/`` where this repository's static analysis runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import highspy

# What a column may hold at most: one whole fiber segment. Nothing is bought twice, so a
# row asking for more than the segments crossing it can hold is a row no design can meet.
_WHOLE = 1.0

# The solver itself, held under a name of its own. ``highspy.Highs`` is written without type
# annotations, so calling it where it is spelled reads as a call into untyped code and
# ``mypy --strict`` refuses it; through this name it is the ordinary callable the one line
# below needs, and no directive is written into the source to say so.
_SOLVER: Any = highspy.Highs


@dataclass(frozen=True)
class SegmentRow:
    """One requirement: these columns, taken together, hold at least ``floor``."""

    columns: tuple[int, ...]
    floor: float


@dataclass(frozen=True)
class SegmentProgram:
    """The whole choice: what each column costs, what is already bought, what must hold.

    ``miles`` is one entry per fiber segment, in column order. ``bought`` are the columns
    an earlier round has already settled on, held at a whole segment each. ``rows`` are the
    requirements the answer has to meet.
    """

    miles: tuple[float, ...]
    bought: frozenset[int]
    rows: tuple[SegmentRow, ...]


@dataclass(frozen=True)
class SegmentChoice:
    """What the solver came back with: the fewest miles, and how much of each segment."""

    miles: float
    held: tuple[float, ...]


def _model(program: SegmentProgram) -> Any:
    """The solver's own description of the choice: columns, their bounds, and the rows."""
    model: Any = highspy.HighsLp()
    model.num_col_ = len(program.miles)
    model.num_row_ = len(program.rows)
    model.col_cost_ = list(program.miles)
    model.col_lower_ = [
        _WHOLE if column in program.bought else 0.0 for column in range(len(program.miles))
    ]
    model.col_upper_ = [_WHOLE] * len(program.miles)
    model.row_lower_ = [row.floor for row in program.rows]
    model.row_upper_ = [highspy.kHighsInf] * len(program.rows)
    model.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
    starts, indices = _matrix(program.rows)
    model.a_matrix_.start_ = starts
    model.a_matrix_.index_ = indices
    model.a_matrix_.value_ = [_WHOLE] * len(indices)
    return model


def _matrix(rows: tuple[SegmentRow, ...]) -> tuple[list[int], list[int]]:
    """Where each row's columns begin, and the columns themselves, laid end to end."""
    starts = [0]
    indices: list[int] = []
    for row in rows:
        indices.extend(row.columns)
        starts.append(len(indices))
    return starts, indices


def _quiet_solver(program: SegmentProgram) -> Any:
    """A solver holding this program and printing nothing, ready to be run."""
    solver: Any = _SOLVER()
    solver.setOptionValue("output_flag", False)
    solver.passModel(_model(program))
    return solver


def _answer(solver: Any) -> SegmentChoice:
    """What the solver reached: the fewest miles, and how much of each segment that holds.

    A program with no answer at all is a defect rather than a finding: every row records a
    separation the fiber in hand could close by buying more of the segments that cross it,
    so a row nothing can meet means the requirements were never capped against the fiber.
    It is raised by name rather than returned, because a design built on a silent zero
    would be fiber nobody can order.
    """
    if solver.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise ValueError(
            "No fiber holding meets every requirement asked of it; the requirements were "
            "not capped against the fiber that is actually there"
        )
    return SegmentChoice(
        float(solver.getObjectiveValue()),
        tuple(float(held) for held in solver.getSolution().col_value),
    )


def solve(program: SegmentProgram) -> SegmentChoice:
    """The fewest miles the rows allow, and how much of each segment that answer holds."""
    solver = _quiet_solver(program)
    solver.run()
    return _answer(solver)


class GrowingSegmentProgram:
    """One solver kept alive while a search writes its rows, instead of one solver a row.

    A search does not know its own requirements when it starts. It solves, looks at the
    answer for a requirement that answer misses, writes that down, and solves again, so the
    program grows by a few rows at a time and is solved hundreds of times before it
    settles. Handing the whole of it to a new solver on every pass throws away the answer
    the pass before had already reached and re-solves from nothing, which is where almost
    all of a build's time went: 96.2% of Two-Node's fiber choice and 91.9% of Minuteman's,
    against 3.7% and 8.0% for the separation search that the passes exist to run (GitHub
    issue #63).

    This holds the columns once and takes the rows as they are found, so each pass starts
    from where the last one finished. The answers are the same answers; what changes is
    that a national map's fiber choice fits inside the fifteen minutes AWS allows a Lambda.
    """

    def __init__(self, miles: tuple[float, ...]) -> None:
        """Open a program over these fiber segments with nothing yet asked of them."""
        self._solver = _quiet_solver(SegmentProgram(miles, frozenset(), ()))
        self._whole: set[int] = set()

    def add_rows(self, rows: tuple[SegmentRow, ...]) -> None:
        """Write these requirements into the program the solver is already holding."""
        if not rows:
            return
        starts, indices = _matrix(rows)
        self._solver.addRows(
            len(rows),
            [row.floor for row in rows],
            [highspy.kHighsInf] * len(rows),
            len(indices),
            starts[:-1],
            indices,
            [_WHOLE] * len(indices),
        )

    def hold_whole(self, columns: frozenset[int]) -> None:
        """Hold these columns at a whole segment each, as a round that bought them asks."""
        for column in sorted(columns - self._whole):
            self._solver.changeColBounds(column, _WHOLE, _WHOLE)
        self._whole |= columns

    def hold_nothing(self) -> None:
        """Let every column back down to none of it, which is what a floor is measured over.

        A floor under the whole problem may take nothing about this particular search for
        granted, so the segments its rounds bought stop being held before it is computed.
        """
        for column in sorted(self._whole):
            self._solver.changeColBounds(column, 0.0, _WHOLE)
        self._whole.clear()

    def solve(self) -> SegmentChoice:
        """Run on from the answer the last pass reached, and read back what it holds."""
        self._solver.run()
        return _answer(self._solver)
