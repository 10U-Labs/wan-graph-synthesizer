"""Unit tests for what the shared write behaviour does when a subclass supplies nothing.

The write side is the same behaviour whichever way a resource is addressed, so it is
written once and each endpoint supplies only the two events it is addressed by. A subclass
that supplies neither is a contract nobody finished binding, and the tests it inherits
would otherwise run against events built from a class attribute that is not there --
failing somewhere inside a handler, naming the handler.
"""

from __future__ import annotations

from typing import Any

import pytest

from test_handler_contracts import WriteBehaviour


class _NeitherEventSupplied(WriteBehaviour):
    """The shared write behaviour as a subclass that bound neither of its two events."""

    CFG: dict[str, Any] = {}

    def ask_for_a_put(self) -> dict[str, Any]:
        """Ask for a PUT event this subclass never said how to build."""
        return self._put_event("vertices", [])

    def ask_for_a_delete(self) -> dict[str, Any]:
        """Ask for a DELETE event this subclass never said how to build."""
        return self._delete_event()


def test_a_subclass_that_binds_no_put_event_is_refused() -> None:
    """There is no sensible event to invent, so the omission is reported where it is made."""
    with pytest.raises(NotImplementedError):
        _NeitherEventSupplied().ask_for_a_put()


def test_a_subclass_that_binds_no_delete_event_is_refused() -> None:
    """The removing request differs by endpoint too, and is not guessed at either."""
    with pytest.raises(NotImplementedError):
        _NeitherEventSupplied().ask_for_a_delete()
