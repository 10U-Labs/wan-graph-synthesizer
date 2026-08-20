"""Unit tests for the PUT event a write-side case is made of.

A handler is judged on what it does with a request, so the request is the input of every
write test there is. Four of its parts decide which code the handler runs: the method, the
resource named in the path parameters, the collection named in the path, and the body. An
event built with the wrong collection is answered 404 by a handler doing exactly as it
should, and the run reads as a handler that lost a collection it has.
"""

from __future__ import annotations

import json
from typing import Any

from test_handler_contracts import write_event

_CFG: dict[str, Any] = {"endpoint": "carriers", "param": "carrier", "id": "zayo"}


def test_the_event_is_a_write() -> None:
    """The read side has its own events; this one exists to be answered by the write side."""
    assert write_event(_CFG, "sites", [])["httpMethod"] == "PUT"


def test_the_resource_is_named_where_the_gateway_names_it() -> None:
    """A handler addressed by id reads that id out of the path parameters and nowhere else."""
    assert write_event(_CFG, "sites", [])["pathParameters"] == {"carrier": "zayo"}


def test_the_collection_asked_for_is_named_in_the_path() -> None:
    """Which of the resource's collections is being replaced is decided by the path."""
    assert write_event(_CFG, "links", [])["path"] == "/x/carriers/zayo/fiber-segments"


def test_the_rows_are_carried_as_the_body_a_gateway_would_deliver() -> None:
    """API Gateway hands a handler text, so the rows arrive encoded rather than as objects."""
    rows = [{"a_municipality": "Denver", "z_municipality": "Reston"}]
    assert json.loads(write_event(_CFG, "links", rows)["body"]) == rows
