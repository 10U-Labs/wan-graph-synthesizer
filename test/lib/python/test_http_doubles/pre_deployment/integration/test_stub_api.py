from __future__ import annotations

import socket
import urllib.error
import urllib.parse
import urllib.request

from test_http_doubles import EMPTY_LISTING, StubApi


def _send(api: StubApi, method: str, path: str, body: bytes | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(f"{api.url}{path}", data=body, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return int(response.status), bytes(response.read())
    except urllib.error.HTTPError as refused:
        status, body = int(refused.code), bytes(refused.read())
        refused.close()
        return status, body


def _send_raw(api: StubApi, payload: bytes) -> None:
    parts = urllib.parse.urlsplit(api.url)
    with socket.create_connection((parts.hostname or "", parts.port or 0), timeout=10) as sock:
        sock.sendall(payload)
        sock.shutdown(socket.SHUT_WR)
        sock.recv(4096)


def test_the_stub_listens_on_loopback() -> None:
    with StubApi() as api:
        assert urllib.parse.urlsplit(api.url).hostname == "127.0.0.1"


def test_the_method_a_client_used_is_recorded() -> None:
    with StubApi() as api:
        _send(api, "PUT", "/carriers/lumen/pops", b"[]")
        assert [method for method, _path, _body in api.records] == ["PUT"]


def test_the_path_a_client_addressed_is_recorded() -> None:
    with StubApi() as api:
        _send(api, "PUT", "/carriers/lumen/pops", b"[]")
        assert [path for _method, path, _body in api.records] == ["/carriers/lumen/pops"]


def test_the_body_a_client_sent_is_recorded() -> None:
    with StubApi() as api:
        _send(api, "PUT", "/tenants/daf/label", b'{"name": "daf"}')
        assert [body for _method, _path, body in api.records] == ['{"name": "daf"}']


def test_a_request_carrying_no_body_records_an_empty_one() -> None:
    with StubApi() as api:
        _send(api, "POST", "/tenants/daf/wan")
        assert [body for _method, _path, body in api.records] == [""]


def test_every_request_is_recorded_in_the_order_it_arrived() -> None:
    with StubApi() as api:
        _send(api, "PUT", "/carriers/lumen/pops", b"[]")
        _send(api, "POST", "/tenants/daf/wan")
        assert [path for _method, path, _body in api.records] == [
            "/carriers/lumen/pops",
            "/tenants/daf/wan",
        ]


def test_the_status_answered_is_the_one_the_stub_was_built_with() -> None:
    with StubApi(status=500) as api:
        assert _send(api, "PUT", "/carriers/lumen/pops", b"[]")[0] == 500


def test_a_request_is_answered_successfully_by_default() -> None:
    with StubApi() as api:
        assert _send(api, "PUT", "/carriers/lumen/pops", b"[]")[0] == 200


def test_the_body_answered_is_the_one_the_stub_was_built_with() -> None:
    with StubApi(body=b'[{"id": "f-35"}]') as api:
        assert _send(api, "GET", "/tenants")[1] == b'[{"id": "f-35"}]'


def test_an_answer_nobody_shaped_is_an_empty_listing() -> None:
    with StubApi() as api:
        assert _send(api, "GET", "/tenants")[1] == EMPTY_LISTING


def test_a_request_the_stub_cannot_read_is_recorded_as_neither_method_nor_path() -> None:
    with StubApi() as api:
        _send_raw(api, b"\r\n\r\n")
        assert api.records == [("", "", "")]
