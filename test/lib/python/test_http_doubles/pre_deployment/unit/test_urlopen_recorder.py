"""Unit tests for the stand-in that records what a client would have sent.

``scripts/seed.py`` delivers the operator's inputs by making HTTP requests, and its unit
tests judge it on the requests it makes: the method, the path and the body. This double
stands in for ``urllib.request.urlopen`` so that judgement costs no network and no API.

A recorder that dropped a request would report a seed run that delivered nothing as one
that delivered everything asked of it, since the recorded list is the only witness.
"""

from __future__ import annotations

import urllib.request

import pytest

from test_http_doubles import EMPTY_LISTING, UrlopenRecorder

_BASE = "https://api.example.test/wan-synthesizer"


def _request(url: str) -> urllib.request.Request:
    """A GET the recorder can be handed, addressed under the base above."""
    return urllib.request.Request(url)


def test_the_request_made_is_the_one_recorded() -> None:
    """What a client sent is read back off the recorder and nowhere else."""
    recorder = UrlopenRecorder()
    recorder(_request(f"{_BASE}/carriers"))
    assert [request.full_url for request in recorder.requests] == [f"{_BASE}/carriers"]


def test_every_request_is_recorded_in_the_order_it_was_made() -> None:
    """A seed run's order of delivery is part of what its tests assert."""
    recorder = UrlopenRecorder()
    recorder(_request(f"{_BASE}/carriers"))
    recorder(_request(f"{_BASE}/tenants"))
    assert len(recorder.requests) == 2


def test_a_recorder_nobody_called_has_recorded_nothing() -> None:
    """A test asserting that nothing was sent needs the list to start out empty."""
    assert len(UrlopenRecorder().requests) == 0


def test_the_paths_are_reported_with_the_base_removed() -> None:
    """A test asserts on the resource path, which is the part the base does not fix."""
    recorder = UrlopenRecorder()
    recorder(_request(f"{_BASE}/carriers/lumen/pops"))
    assert recorder.paths(_BASE) == ["carriers/lumen/pops"]


def test_the_answer_carries_the_body_the_recorder_was_built_with() -> None:
    """A client that reads what it fetched is exercised by shaping the answer."""
    recorder = UrlopenRecorder(body=b'[{"id": "f-35"}]')
    assert recorder(_request(f"{_BASE}/tenants")).read() == b'[{"id": "f-35"}]'


def test_the_answer_carries_the_status_the_recorder_was_built_with() -> None:
    """A client that branches on failure is exercised the same way."""
    recorder = UrlopenRecorder(status=500)
    assert recorder(_request(f"{_BASE}/tenants")).status == 500


def test_an_answer_nobody_shaped_is_a_successful_empty_listing() -> None:
    """The common case is a write whose answer is not read, and that answer still parses."""
    assert UrlopenRecorder()(_request(f"{_BASE}/tenants")).read() == EMPTY_LISTING


def test_a_timeout_the_client_sets_is_accepted_and_ignored() -> None:
    """The client under test passes one, and there is no socket here for it to bound."""
    recorder = UrlopenRecorder()
    recorder(_request(f"{_BASE}/tenants"), timeout=30.0)
    assert len(recorder.requests) == 1


def test_a_failure_the_recorder_was_built_with_is_raised_in_place_of_an_answer() -> None:
    """A client that copes with a dropped connection needs one to cope with."""
    recorder = UrlopenRecorder(failures=[ConnectionResetError(104, "Connection reset by peer")])
    with pytest.raises(ConnectionResetError):
        recorder(_request(f"{_BASE}/tenants"))


def test_the_request_that_failed_is_recorded_before_it_fails() -> None:
    """A client that retries is judged on the attempts it made, so a failed one counts."""
    recorder = UrlopenRecorder(failures=[ConnectionResetError()])
    with pytest.raises(ConnectionResetError):
        recorder(_request(f"{_BASE}/tenants"))
    assert len(recorder.requests) == 1


def test_the_failures_are_raised_oldest_first() -> None:
    """A client whose second attempt fails differently is exercised by the order."""
    recorder = UrlopenRecorder(failures=[ConnectionResetError(), TimeoutError()])
    with pytest.raises(ConnectionResetError):
        recorder(_request(f"{_BASE}/tenants"))
    with pytest.raises(TimeoutError):
        recorder(_request(f"{_BASE}/tenants"))


def test_the_recorder_answers_once_its_failures_are_spent() -> None:
    """A retry that succeeds is the case the client is written for."""
    recorder = UrlopenRecorder(body=b'[{"id": "f-35"}]', failures=[ConnectionResetError()])
    with pytest.raises(ConnectionResetError):
        recorder(_request(f"{_BASE}/tenants"))
    assert recorder(_request(f"{_BASE}/tenants")).read() == b'[{"id": "f-35"}]'
