from __future__ import annotations

import socketserver
import threading
import urllib.request
from collections.abc import Sequence
from typing import Any, cast

EMPTY_LISTING = b"[]"


class FakeResponse:
    def __init__(self, status: int = 200, body: bytes = EMPTY_LISTING) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class UrlopenRecorder:
    def __init__(
            self, status: int = 200, body: bytes = EMPTY_LISTING,
            failures: Sequence[BaseException] = (),
    ) -> None:
        self.requests: list[urllib.request.Request] = []
        self._status = status
        self._body = body
        self._failures = list(failures)

    def __call__(
            self, request: urllib.request.Request, timeout: float = 0.0,
    ) -> FakeResponse:
        del timeout
        self.requests.append(request)
        if self._failures:
            raise self._failures.pop(0)
        return FakeResponse(self._status, self._body)

    def paths(self, base: str) -> list[str]:
        prefix = f"{base}/"
        return [request.full_url[len(prefix):] for request in self.requests]


class CallRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, *args: Any) -> None:
        self.calls.append(args)

    def nth(self, index: int) -> list[Any]:
        return [call[index] for call in self.calls]


class _RecordingHandler(socketserver.StreamRequestHandler):
    def read_request(self) -> tuple[str, str, str]:
        request_line = self.rfile.readline().decode("ascii", "replace")
        parts = request_line.split()
        method, path = (parts[0], parts[1]) if len(parts) >= 2 else ("", "")
        length = 0
        while True:
            header = self.rfile.readline().decode("ascii", "replace").strip()
            if not header:
                break
            name, _, value = header.partition(":")
            if name.strip().lower() == "content-length":
                length = int(value.strip() or "0")
        return method, path, self.rfile.read(length).decode("utf-8", "replace")

    def handle(self) -> None:
        server = cast("_RecordingServer", self.server)
        server.records.append(self.read_request())
        reason = "OK" if server.status < 400 else "Error"
        self.wfile.write(
            f"HTTP/1.1 {server.status} {reason}\r\n"
            f"Content-Length: {len(server.body)}\r\n"
            "Connection: close\r\n\r\n".encode("ascii"),
        )
        self.wfile.write(server.body)


class _RecordingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, status: int, body: bytes) -> None:
        self.records: list[tuple[str, str, str]] = []
        self.status = status
        self.body = body
        super().__init__(("127.0.0.1", 0), _RecordingHandler)


class StubApi:
    def __init__(self, status: int = 200, body: bytes = EMPTY_LISTING) -> None:
        self._server = _RecordingServer(status, body)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        address = cast("tuple[str, int]", self._server.server_address)
        return f"http://127.0.0.1:{address[1]}"

    @property
    def records(self) -> list[tuple[str, str, str]]:
        return self._server.records

    def __enter__(self) -> "StubApi":
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
