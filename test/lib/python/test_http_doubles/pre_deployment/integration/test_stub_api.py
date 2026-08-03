"""The stub API answers a real request and records what it was sent.

``scripts/seed.py`` is driven as a subprocess in the tier that owns this file, and a
subprocess cannot be handed an in-process double: it opens a socket and speaks HTTP. The
stub is the far end of that socket. It is the only thing standing between those tests and
a live API, so what it records is the whole of what they know about what seed delivered.

This is where the module stops being exercisable by literals. Two real units are put
against each other -- a client speaking HTTP and the server reading it -- and nothing
outside the process is reached: the server is opened by the test on a loopback port the
operating system picks, and closed again on the way out.
"""

from __future__ import annotations

import socket
import urllib.error
import urllib.parse
import urllib.request

from test_http_doubles import EMPTY_LISTING, StubApi


def _send(api: StubApi, method: str, path: str, body: bytes | None = None) -> tuple[int, bytes]:
    """Make one request of the stub and return the status and body it answered with."""
    request = urllib.request.Request(f"{api.url}{path}", data=body, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return int(response.status), bytes(response.read())
    except urllib.error.HTTPError as refused:
        status, body = int(refused.code), bytes(refused.read())
        refused.close()
        return status, body


def _send_raw(api: StubApi, payload: bytes) -> None:
    """Write *payload* straight onto the socket, for a request no client would send."""
    parts = urllib.parse.urlsplit(api.url)
    with socket.create_connection((parts.hostname or "", parts.port or 0), timeout=10) as sock:
        sock.sendall(payload)
        sock.shutdown(socket.SHUT_WR)
        sock.recv(4096)


def test_the_stub_listens_on_loopback() -> None:
    """Nothing off this machine can reach it, which is what makes it safe to run anywhere."""
    with StubApi() as api:
        assert urllib.parse.urlsplit(api.url).hostname == "127.0.0.1"


def test_the_method_a_client_used_is_recorded() -> None:
    """A seed run is judged on writing with PUT and building with POST."""
    with StubApi() as api:
        _send(api, "PUT", "/carriers/lumen/vertices", b"[]")
        assert [method for method, _path, _body in api.records] == ["PUT"]


def test_the_path_a_client_addressed_is_recorded() -> None:
    """Which resource was written is the other half of that judgement."""
    with StubApi() as api:
        _send(api, "PUT", "/carriers/lumen/vertices", b"[]")
        assert [path for _method, path, _body in api.records] == ["/carriers/lumen/vertices"]


def test_the_body_a_client_sent_is_recorded() -> None:
    """The rows delivered are read back out of the record, so the whole body has to arrive."""
    with StubApi() as api:
        _send(api, "PUT", "/tenants/daf/label", b'{"name": "daf"}')
        assert [body for _method, _path, body in api.records] == ['{"name": "daf"}']


def test_a_request_carrying_no_body_records_an_empty_one() -> None:
    """A POST that starts a build sends nothing, and that is not a body gone missing."""
    with StubApi() as api:
        _send(api, "POST", "/tenants/daf/wan")
        assert [body for _method, _path, body in api.records] == [""]


def test_every_request_is_recorded_in_the_order_it_arrived() -> None:
    """Seed delivers inputs before it asks for a build, and the order is what says so."""
    with StubApi() as api:
        _send(api, "PUT", "/carriers/lumen/vertices", b"[]")
        _send(api, "POST", "/tenants/daf/wan")
        assert [path for _method, path, _body in api.records] == [
            "/carriers/lumen/vertices",
            "/tenants/daf/wan",
        ]


def test_the_status_answered_is_the_one_the_stub_was_built_with() -> None:
    """A client that must survive a refusal is exercised by a stub that refuses."""
    with StubApi(status=500) as api:
        assert _send(api, "PUT", "/carriers/lumen/vertices", b"[]")[0] == 500


def test_a_request_is_answered_successfully_by_default() -> None:
    """The ordinary case is a call that worked, so that is what a bare stub answers."""
    with StubApi() as api:
        assert _send(api, "PUT", "/carriers/lumen/vertices", b"[]")[0] == 200


def test_the_body_answered_is_the_one_the_stub_was_built_with() -> None:
    """A client that reads what it fetched needs an answer worth reading."""
    with StubApi(body=b'[{"id": "f-35"}]') as api:
        assert _send(api, "GET", "/tenants")[1] == b'[{"id": "f-35"}]'


def test_an_answer_nobody_shaped_is_an_empty_listing() -> None:
    """A client that parses every answer gets something that parses, whatever it asked for."""
    with StubApi() as api:
        assert _send(api, "GET", "/tenants")[1] == EMPTY_LISTING


def test_a_request_the_stub_cannot_read_is_recorded_as_neither_method_nor_path() -> None:
    """A malformed line is recorded as the nothing it was, rather than half-read as a request."""
    with StubApi() as api:
        _send_raw(api, b"\r\n\r\n")
        assert api.records == [("", "", "")]
