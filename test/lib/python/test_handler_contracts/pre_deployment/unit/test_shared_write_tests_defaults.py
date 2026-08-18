"""Unit tests for what the shared write behaviour does when a subclass supplies nothing.

The write side is the same behaviour whichever way a resource is addressed, so it is
written once and each endpoint supplies only the two events it is addressed by. A subclass
that supplies neither is a contract nobody finished binding, and the tests it inherits
would otherwise run against events built from nothing -- failing somewhere inside a
handler, and naming the handler.

Both methods are reached through ``getattr`` on the shared class itself. A subclass would
be the natural way to ask, and it cannot ask this question: one that overrode the two
methods would no longer be the subclass that supplied neither, and one that did not
override them is a concrete class inheriting an unimplemented method, which is the thing
the linter refuses.
"""

from __future__ import annotations

import pytest

from test_handler_contracts import SharedWriteTests


def test_a_subclass_that_binds_no_put_event_is_refused() -> None:
    """There is no sensible event to invent, so the omission is reported where it is made."""
    with pytest.raises(NotImplementedError):
        getattr(SharedWriteTests(), "_put_event")("vertices", [])


def test_a_subclass_that_binds_no_delete_event_is_refused() -> None:
    """The removing request differs by endpoint too, and is not guessed at either."""
    with pytest.raises(NotImplementedError):
        getattr(SharedWriteTests(), "_delete_event")()
