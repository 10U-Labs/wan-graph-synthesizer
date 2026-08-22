from __future__ import annotations

from test_http_doubles import CallRecorder


def test_the_arguments_of_a_call_are_recorded_as_they_were_passed() -> None:
    recorder = CallRecorder()
    recorder("carriers/lumen/pops", [{"id": "P0"}])
    assert recorder.calls == [("carriers/lumen/pops", [{"id": "P0"}])]


def test_a_recorder_nobody_called_has_recorded_nothing() -> None:
    assert len(CallRecorder().calls) == 0


def test_every_call_is_recorded_in_the_order_it_was_made() -> None:
    recorder = CallRecorder()
    recorder("carriers/lumen/pops")
    recorder("tenants/daf/label")
    assert len(recorder.calls) == 2


def test_one_argument_position_is_reported_across_every_call() -> None:
    recorder = CallRecorder()
    recorder("carriers/lumen/pops", [])
    recorder("tenants/daf/label", [])
    assert recorder.nth(0) == ["carriers/lumen/pops", "tenants/daf/label"]


def test_a_later_argument_position_is_reported_the_same_way() -> None:
    recorder = CallRecorder()
    recorder("tenants/daf/label", {"name": "daf"})
    assert recorder.nth(1) == [{"name": "daf"}]
