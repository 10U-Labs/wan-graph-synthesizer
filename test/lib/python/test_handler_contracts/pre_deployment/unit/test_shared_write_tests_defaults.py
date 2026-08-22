from __future__ import annotations

import pytest

from test_handler_contracts import SharedWriteTests


def test_a_subclass_that_binds_no_put_event_is_refused() -> None:
    with pytest.raises(NotImplementedError):
        getattr(SharedWriteTests(), "_put_event")("sites", [])


def test_a_subclass_that_binds_no_delete_event_is_refused() -> None:
    with pytest.raises(NotImplementedError):
        getattr(SharedWriteTests(), "_delete_event")()
