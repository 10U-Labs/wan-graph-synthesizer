"""Unit tests for the CSPs endpoint Lambda handler.

The CSP endpoint is a plain instance of the shared read/write framework, so its
tests are exactly the two contracts bound to the CSP endpoint's data.
"""

from __future__ import annotations

from typing import Any

from test_handler_contracts import ReaderContract, WriterContract

_READER: dict[str, Any] = {
    "endpoint": "csps",
    "list_keys": ["csps/aws/vertices.json", "csps/azure/vertices.json"],
    "ids": ["aws", "azure"],
    "stored_key": "csps/aws/vertices.json",
    "stored": [{"id": "us-east"}],
    "serve_event": {
        "pathParameters": {"provider": "aws"},
        "path": "/x/csps/aws/vertices",
    },
    "serve_expect": [{"id": "us-east"}],
    "unknown_event": {
        "pathParameters": {"provider": "aws"},
        "path": "/x/csps/aws/edges",
    },
    "notbuilt_event": {
        "pathParameters": {"provider": "oci"},
        "path": "/x/csps/oci/vertices",
    },
}

_WRITER: dict[str, Any] = {
    "endpoint": "csps",
    "param": "provider",
    "key": "csps/aws/vertices.json",
    "id": "aws",
    "valid": [{"name": "r", "municipality": "Denver", "state": "CO",
               "country": "United States", "latitude": 1.0, "longitude": 2.0}],
}


class TestCspsReader(ReaderContract):
    """The shared read-side contract, applied to the CSPs endpoint."""

    CFG = _READER


class TestCspsWriter(WriterContract):
    """The shared write-side contract, applied to the CSPs endpoint."""

    CFG = _WRITER
