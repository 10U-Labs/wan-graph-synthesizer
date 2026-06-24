"""Reusable, network-free HTTP test doubles.

``UrlopenRecorder`` replaces ``urllib.request.urlopen`` in-process so unit and
integration tests can assert what a client would send without touching the
network. ``StubApi`` runs a real localhost server that records the requests it
receives, for end-to-end tests that drive a CLI as a subprocess. ``CallRecorder``
records arbitrary calls. No live resource is ever touched.
"""

from __future__ import annotations

import socketserver
import threading
import urllib.request
from typing import Any, cast


class FakeResponse:
    """A context-manager stand-in for an HTTP response object."""

    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        """Leave the context; there is nothing to clean up."""
        return None


class UrlopenRecorder:
    """A drop-in for ``urllib.request.urlopen`` that records its requests."""

    def __init__(self, status: int = 200) -> None:
        self.requests: list[urllib.request.Request] = []
        self._status = status

    def __call__(
            self, request: urllib.request.Request, timeout: float = 0.0,
    ) -> FakeResponse:
        """Record *request* and return a fake response with the fixed status."""
        del timeout
        self.requests.append(request)
        return FakeResponse(self._status)

    def paths(self, base: str) -> list[str]:
        """Recorded resource paths with the ``{base}/`` prefix removed."""
        prefix = f"{base}/"
        return [request.full_url[len(prefix):] for request in self.requests]


class CallRecorder:
    """Record the positional arguments of each call made to it."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def __call__(self, *args: Any) -> None:
        """Record one call's positional arguments."""
        self.calls.append(args)


class _RecordingHandler(socketserver.StreamRequestHandler):
    """Read one HTTP request, record it, and reply with the server's status."""

    def handle(self) -> None:
        """Parse the request line, headers, and body; record then respond."""
        server = cast("_RecordingServer", self.server)
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
        body = self.rfile.read(length).decode("utf-8", "replace")
        server.records.append((method, path, body))
        reason = "OK" if server.status < 400 else "Error"
        self.wfile.write(
            f"HTTP/1.1 {server.status} {reason}\r\n"
            "Content-Length: 0\r\n"
            "Connection: close\r\n\r\n".encode("ascii"),
        )


class _RecordingServer(socketserver.ThreadingTCPServer):
    """A threaded TCP server that records the requests its handler receives."""

    allow_reuse_address = True

    def __init__(self, status: int) -> None:
        self.records: list[tuple[str, str, str]] = []
        self.status = status
        super().__init__(("127.0.0.1", 0), _RecordingHandler)


class StubApi:
    """A localhost HTTP server that records PUTs and replies with a status."""

    def __init__(self, status: int = 200) -> None:
        self._server = _RecordingServer(status)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        """The base URL clients should target, e.g. ``http://127.0.0.1:54321``."""
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}"

    @property
    def records(self) -> list[tuple[str, str, str]]:
        """The (method, path, body) of every request received so far."""
        return self._server.records

    def __enter__(self) -> "StubApi":
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        """Stop serving and release the socket."""
        self._server.shutdown()
        self._server.server_close()
