"""Unit tests for the carriers endpoint Lambda handler.

The read/write behaviour shared with the other framework endpoints comes from the
contracts; the carrier-specific links columns and per-collection isolation are here.
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
    "list_keys": ["carriers/lumen/pops.json", "carriers/zayo/pops.json"],
    "ids": ["lumen", "zayo"],
    "stored_key": "carriers/lumen/pops.json",
    "stored": [{"id": "P"}],
    "serve_event": {
        "pathParameters": {"carrier": "lumen"},
        "path": "/x/carriers/lumen/pops",
    },
    "serve_expect": [{"id": "P"}],
    "unknown_event": {
        "pathParameters": {"carrier": "lumen"},
        "path": "/x/carriers/lumen/bogus",
    },
    "notbuilt_event": {
        "pathParameters": {"carrier": "zayo"},
        "path": "/x/carriers/zayo/fiber-segments",
    },
}

_WRITER: dict[str, Any] = {
    "endpoint": "carriers",
    "param": "carrier",
    "key": "carriers/lumen/pops.json",
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


def test_carrier_fiber_segments_accept_the_endpoint_columns(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A carrier fiber-segments PUT with the four endpoint columns is stored."""
    module = load_handler("carriers", monkeypatch)
    objects: dict[str, bytes] = {}
    row = {"a_municipality": "A", "a_state": "X", "z_municipality": "B", "z_state": "Y"}
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(write_event(_WRITER, "fiber-segments", [row]), None)
    assert json.loads(objects["carriers/lumen/fiber-segments.json"]) == [row]


def test_carrier_put_leaves_the_other_collection_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """A carrier sites PUT writes only the sites file, leaving links untouched."""
    module = load_handler("carriers", monkeypatch)
    objects = {"carriers/lumen/fiber-segments.json": json.dumps([{"e": 1}]).encode()}
    event = write_event(_WRITER, "pops", _WRITER["valid"])
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(event, None)
    assert json.loads(objects["carriers/lumen/fiber-segments.json"]) == [{"e": 1}]
