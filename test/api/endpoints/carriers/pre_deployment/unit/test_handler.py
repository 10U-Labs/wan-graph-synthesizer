"""Unit tests for the carriers endpoint Lambda handler.

The read/write behaviour shared with the other framework endpoints comes from the
contracts; the carrier-specific edges columns and per-collection isolation are here.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from test_handler_contracts import (
    ReaderContract,
    WriterContract,
    load_handler,
    write_clients,
    write_event,
)

_READER: dict[str, Any] = {
    "endpoint": "carriers",
    "list_keys": ["carriers/lumen/vertices.json", "carriers/zayo/vertices.json"],
    "ids": ["lumen", "zayo"],
    "stored_key": "carriers/lumen/vertices.json",
    "stored": [{"id": "P"}],
    "serve_event": {
        "pathParameters": {"carrier": "lumen"},
        "path": "/x/carriers/lumen/vertices",
    },
    "serve_expect": [{"id": "P"}],
    "unknown_event": {
        "pathParameters": {"carrier": "lumen"},
        "path": "/x/carriers/lumen/bogus",
    },
    "notbuilt_event": {
        "pathParameters": {"carrier": "zayo"},
        "path": "/x/carriers/zayo/edges",
    },
}

_WRITER: dict[str, Any] = {
    "endpoint": "carriers",
    "param": "carrier",
    "key": "carriers/lumen/vertices.json",
    "id": "lumen",
    "valid": [{"municipality": "Denver", "state": "CO", "country": "United States",
               "latitude": 1.0, "longitude": 2.0}],
}


class TestCarriersReader(ReaderContract):
    """The shared read-side contract, applied to the carriers endpoint."""

    CFG = _READER


class TestCarriersWriter(WriterContract):
    """The shared write-side contract, applied to the carriers endpoint."""

    CFG = _WRITER


def test_carrier_edges_accept_the_endpoint_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    """A carrier edges PUT with the four endpoint columns is stored."""
    module = load_handler("carriers", monkeypatch)
    objects: dict[str, bytes] = {}
    row = {"a_municipality": "A", "a_state": "X", "z_municipality": "B", "z_state": "Y"}
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(write_event(_WRITER, "edges", [row]), None)
    assert json.loads(objects["carriers/lumen/edges.json"]) == [row]


def test_carrier_put_leaves_the_other_collection_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """A carrier vertices PUT writes only the vertices file, leaving edges untouched."""
    module = load_handler("carriers", monkeypatch)
    objects = {"carriers/lumen/edges.json": json.dumps([{"e": 1}]).encode()}
    event = write_event(_WRITER, "vertices", _WRITER["valid"])
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(event, None)
    assert json.loads(objects["carriers/lumen/edges.json"]) == [{"e": 1}]
