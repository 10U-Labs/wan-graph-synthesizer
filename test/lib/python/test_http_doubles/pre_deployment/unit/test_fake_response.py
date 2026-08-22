from __future__ import annotations

from test_http_doubles import EMPTY_LISTING, FakeResponse


def test_the_body_read_is_the_body_it_was_built_with() -> None:
    assert FakeResponse(body=b'[{"id": "f-35"}]').read() == b'[{"id": "f-35"}]'


def test_an_answer_nobody_shaped_is_an_empty_listing() -> None:
    assert FakeResponse().read() == EMPTY_LISTING


def test_the_status_is_the_one_it_was_built_with() -> None:
    assert FakeResponse(status=500).status == 500


def test_an_answer_nobody_shaped_reports_success() -> None:
    assert FakeResponse().status == 200


def test_entering_the_answer_yields_the_answer_itself() -> None:
    response = FakeResponse()
    with response as entered:
        assert entered is response


def test_the_body_is_readable_from_inside_the_context() -> None:
    with FakeResponse(body=b'[{"id": "daf"}]') as response:
        assert response.read() == b'[{"id": "daf"}]'
