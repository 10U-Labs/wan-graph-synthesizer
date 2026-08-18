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


def solve(program: SegmentProgram) -> SegmentChoice:
    """The fewest miles the rows allow, and how much of each segment that answer holds.

    A program with no answer at all is a defect rather than a finding: every row records a
    separation the fiber in hand could close by buying more of the segments that cross it,
    so a row nothing can meet means the requirements were never capped against the fiber.
    It is raised by name rather than returned, because a design built on a silent zero
    would be fiber nobody can order.
    """
    solver: Any = _SOLVER()
    solver.setOptionValue("output_flag", False)
    solver.passModel(_model(program))
    solver.run()
    if solver.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise ValueError(
            "No fiber holding meets every requirement asked of it; the requirements were "
            "not capped against the fiber that is actually there"
        )
    return SegmentChoice(
        float(solver.getObjectiveValue()),
        tuple(float(held) for held in solver.getSolution().col_value),
    )
