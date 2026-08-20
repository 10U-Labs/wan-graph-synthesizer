"""Unit tests for the recorder that stands in for a function and remembers its arguments.

Where a test replaces one call a program makes -- the sender that PUTs a collection, say
-- what it wants afterwards is the arguments of every call in order. That is the whole of
this double, and reading one argument position across every call is the question asked of
it most often: which paths were written, in which order.
"""

from __future__ import annotations

from test_http_doubles import CallRecorder


def test_the_arguments_of_a_call_are_recorded_as_they_were_passed() -> None:
    """One call is one tuple, in the order the caller wrote them."""
    recorder = CallRecorder()
    recorder("carriers/lumen/pops", [{"id": "P0"}])
    assert recorder.calls == [("carriers/lumen/pops", [{"id": "P0"}])]


def test_a_recorder_nobody_called_has_recorded_nothing() -> None:
    """A test asserting that the call was never made needs the list to start out empty."""
    assert len(CallRecorder().calls) == 0


def test_every_call_is_recorded_in_the_order_it_was_made() -> None:
    """Delivery order is part of what a seed run promises: inputs before the build."""
    recorder = CallRecorder()
    recorder("carriers/lumen/pops")
    recorder("tenants/daf/label")
    assert len(recorder.calls) == 2


def test_one_argument_position_is_reported_across_every_call() -> None:
    """The paths written are the first argument of each call, and that list is the subject."""
    recorder = CallRecorder()
    recorder("carriers/lumen/pops", [])
    recorder("tenants/daf/label", [])
    assert recorder.nth(0) == ["carriers/lumen/pops", "tenants/daf/label"]


def test_a_later_argument_position_is_reported_the_same_way() -> None:
    """What was written matters as much as where, and it is read back the same way."""
    recorder = CallRecorder()
    recorder("tenants/daf/label", {"name": "daf"})
    assert recorder.nth(1) == [{"name": "daf"}]
