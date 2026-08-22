from __future__ import annotations

import json
from typing import Any

from test_handler_contracts import write_event

_CFG: dict[str, Any] = {"endpoint": "carriers", "param": "carrier", "id": "zayo"}


def test_the_event_is_a_write() -> None:
    assert write_event(_CFG, "sites", [])["httpMethod"] == "PUT"


def test_the_resource_is_named_where_the_gateway_names_it() -> None:
    assert write_event(_CFG, "sites", [])["pathParameters"] == {"carrier": "zayo"}


def test_the_collection_asked_for_is_named_in_the_path() -> None:
    assert write_event(_CFG, "fiber-segments", [])["path"] == "/x/carriers/zayo/fiber-segments"


def test_the_rows_are_carried_as_the_body_a_gateway_would_deliver() -> None:
    rows = [{"a_municipality": "Denver", "z_municipality": "Reston"}]
    assert json.loads(write_event(_CFG, "fiber-segments", rows)["body"]) == rows
