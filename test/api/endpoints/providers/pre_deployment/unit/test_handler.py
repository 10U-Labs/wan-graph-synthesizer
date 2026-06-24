"""Unit tests for the providers endpoint Lambda handler.

The provider endpoint is a plain instance of the shared read/write framework, so its
tests are exactly the two contracts bound to the provider endpoint's data.
"""

from __future__ import annotations

from typing import Any

from test_handler_contracts import ReaderContract, WriterContract

_READER: dict[str, Any] = {
    "endpoint": "providers",
    "list_keys": ["providers", "providers"],
    "ids": ["providers"],
    "stored_key": "providers",
    "stored": [{"id": "us-east"}],
    "serve_event": {
        "pathParameters": {"provider": "aws"},
        "path": "/x/providers",
    },
    "serve_expect": [{"id": "us-east"}],
    "unknown_event": {
        "pathParameters": {"provider": "aws"},
        "path": "/x/providers",
    },
    "notbuilt_event": {
        "pathParameters": {"provider": "provider"},
        "path": "/x/providers",
    },
}

_WRITER: dict[str, Any] = {
    "endpoint": "providers",
    "param": "provider",
    "key": "providers",
    "id": "aws",
    "env": {"WAN_FUNCTION": "wan-fn"},
    "invokes": 2,
    "valid": [{"name": "r", "municipality": "Denver", "state": "CO",
               "latitude": 1.0, "longitude": 2.0}],
}


class TestprovidersReader(ReaderContract):
    """The shared read-side contract, applied to the providers endpoint."""

    CFG = _READER


class TestprovidersWriter(WriterContract):
    """The shared write-side contract, applied to the providers endpoint."""

    CFG = _WRITER
