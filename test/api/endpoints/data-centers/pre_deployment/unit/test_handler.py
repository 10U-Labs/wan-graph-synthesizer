"""Unit tests for the data-centers endpoint Lambda handler.

The data-centers endpoint is a plain instance of the shared read/write framework,
so its tests are exactly the two contracts bound to the data-centers endpoint's data.
"""

from __future__ import annotations

from typing import Any

from test_handler_contracts import ReaderContract, WriterContract

_READER: dict[str, Any] = {
    "endpoint": "data-centers",
    "list_keys": [
        "data-centers/equinix/vertices.json",
        "data-centers/flexential/vertices.json",
        "data-centers/merge/vertices.json",
    ],
    "ids": ["equinix", "flexential"],
    "stored_key": "data-centers/flexential/vertices.json",
    "stored": [{"id": "us-east"}],
    "serve_event": {
        "pathParameters": {"provider": "flexential"},
        "path": "/x/data-centers/flexential/vertices",
    },
    "serve_expect": [{"id": "us-east"}],
    "unknown_event": {
        "pathParameters": {"provider": "flexential"},
        "path": "/x/data-centers/flexential/edges",
    },
    "notbuilt_event": {
        "pathParameters": {"provider": "coresite"},
        "path": "/x/data-centers/coresite/vertices",
    },
}

_WRITER: dict[str, Any] = {
    "endpoint": "data-centers",
    "param": "provider",
    "key": "data-centers/flexential/vertices.json",
    "id": "flexential",
    "valid": [{"municipality": "Denver", "state": "CO",
               "latitude": 1.0, "longitude": 2.0}],
}


class TestDataCentersReader(ReaderContract):
    """The shared read-side contract, applied to the data-centers endpoint."""

    CFG = _READER


class TestDataCentersWriter(WriterContract):
    """The shared write-side contract, applied to the data-centers endpoint."""

    CFG = _WRITER
