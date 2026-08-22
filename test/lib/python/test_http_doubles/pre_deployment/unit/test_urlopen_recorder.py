from __future__ import annotations

import urllib.request

import pytest

from test_http_doubles import EMPTY_LISTING, UrlopenRecorder

_BASE = "https://api.example.test/wan-synthesizer"


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url)


def test_the_request_made_is_the_one_recorded() -> None:
    recorder = UrlopenRecorder()
    recorder(_request(f"{_BASE}/carriers"))
    assert [request.full_url for request in recorder.requests] == [f"{_BASE}/carriers"]


def test_every_request_is_recorded_in_the_order_it_was_made() -> None:
    recorder = UrlopenRecorder()
    recorder(_request(f"{_BASE}/carriers"))
    recorder(_request(f"{_BASE}/tenants"))
    assert len(recorder.requests) == 2


def test_a_recorder_nobody_called_has_recorded_nothing() -> None:
    assert len(UrlopenRecorder().requests) == 0


def test_the_paths_are_reported_with_the_base_removed() -> None:
    recorder = UrlopenRecorder()
    recorder(_request(f"{_BASE}/carriers/lumen/pops"))
    assert recorder.paths(_BASE) == ["carriers/lumen/pops"]


def test_the_answer_carries_the_body_the_recorder_was_built_with() -> None:
    recorder = UrlopenRecorder(body=b'[{"id": "f-35"}]')
    assert recorder(_request(f"{_BASE}/tenants")).read() == b'[{"id": "f-35"}]'


def test_the_answer_carries_the_status_the_recorder_was_built_with() -> None:
    recorder = UrlopenRecorder(status=500)
    assert recorder(_request(f"{_BASE}/tenants")).status == 500


def test_an_answer_nobody_shaped_is_a_successful_empty_listing() -> None:
    assert UrlopenRecorder()(_request(f"{_BASE}/tenants")).read() == EMPTY_LISTING


def test_a_timeout_the_client_sets_is_accepted_and_ignored() -> None:
    recorder = UrlopenRecorder()
    recorder(_request(f"{_BASE}/tenants"), timeout=30.0)
    assert len(recorder.requests) == 1


def _spend_a_failure(recorder: UrlopenRecorder, url: str) -> None:
    try:
        recorder(_request(url))
    except OSError:
        pass


def test_a_failure_the_recorder_was_built_with_is_raised_in_place_of_an_answer() -> None:
    recorder = UrlopenRecorder(failures=[ConnectionResetError(104, "Connection reset by peer")])
    with pytest.raises(ConnectionResetError):
        recorder(_request(f"{_BASE}/tenants"))


def test_the_request_that_failed_is_recorded_before_it_fails() -> None:
    recorder = UrlopenRecorder(failures=[ConnectionResetError()])
    _spend_a_failure(recorder, f"{_BASE}/tenants")
    assert len(recorder.requests) == 1


def test_the_failures_are_raised_oldest_first() -> None:
    recorder = UrlopenRecorder(failures=[ConnectionResetError(), TimeoutError()])
    _spend_a_failure(recorder, f"{_BASE}/tenants")
    with pytest.raises(TimeoutError):
        recorder(_request(f"{_BASE}/tenants"))


def test_the_recorder_answers_once_its_failures_are_spent() -> None:
    recorder = UrlopenRecorder(body=b'[{"id": "f-35"}]', failures=[ConnectionResetError()])
    _spend_a_failure(recorder, f"{_BASE}/tenants")
    assert recorder(_request(f"{_BASE}/tenants")).read() == b'[{"id": "f-35"}]'
