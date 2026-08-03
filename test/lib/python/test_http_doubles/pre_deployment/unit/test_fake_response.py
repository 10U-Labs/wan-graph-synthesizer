"""Unit tests for the stand-in HTTP response a recorded request is answered with.

A client that reads what it fetched -- ``scripts/seed.py`` reads the ids the API already
holds before deciding what to delete -- needs an answer with a body in it, and this is
that answer. It is used the way a real response is used, inside a ``with``, so it has to
survive being entered and left.
"""

from __future__ import annotations

from test_http_doubles import EMPTY_LISTING, FakeResponse


def test_the_body_read_is_the_body_it_was_built_with() -> None:
    """A client parses what it read, so the bytes have to be the caller's own."""
    assert FakeResponse(body=b'[{"id": "f-35"}]').read() == b'[{"id": "f-35"}]'


def test_an_answer_nobody_shaped_is_an_empty_listing() -> None:
    """Most requests are writes whose answer is not read, and an empty listing parses."""
    assert FakeResponse().read() == EMPTY_LISTING


def test_the_status_is_the_one_it_was_built_with() -> None:
    """A client that branches on the status needs the status the case is about."""
    assert FakeResponse(status=500).status == 500


def test_an_answer_nobody_shaped_reports_success() -> None:
    """The ordinary case is a call that worked, so that is what is answered by default."""
    assert FakeResponse().status == 200


def test_entering_the_answer_yields_the_answer_itself() -> None:
    """Clients read inside a ``with``, and what they read is what was handed back."""
    response = FakeResponse()
    with response as entered:
        assert entered is response


def test_the_body_is_readable_from_inside_the_context() -> None:
    """Leaving the context releases nothing, so a client reads exactly as it would in earnest."""
    with FakeResponse(body=b'[{"id": "daf"}]') as response:
        assert response.read() == b'[{"id": "daf"}]'
