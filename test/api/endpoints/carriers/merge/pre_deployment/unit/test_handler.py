"""Unit tests for the carriers/merge endpoint Lambda handler.

Merge is its own resource: POST unions every carrier's points/connections into the
substrate, GET serves the stored substrate. None of this is shared, so it lives here.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from test_handler_contracts import load_handler
from test_s3_store_mock import fake_s3


def _merge_objects() -> dict[str, bytes]:
    """Two carriers' point/connection files: 2 points and 1 connection in total."""
    return {
        "carriers/a/vertices.json": json.dumps([{"municipality": "X"}]).encode(),
        "carriers/a/edges.json": json.dumps([{"a_municipality": "X"}]).encode(),
        "carriers/b/vertices.json": json.dumps([{"municipality": "Y"}]).encode(),
    }


def test_merge_post_unions_carriers(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST counts the points and connections unioned (and skips the merge's own output)."""
    module = load_handler("carriers/merge", monkeypatch)
    objects = _merge_objects()
    fake = fake_s3(objects, keys=[*objects, "carriers/merge/vertices.json"])
    with patch("boto3.client", return_value=fake):
        response = module.lambda_handler({"httpMethod": "POST"}, None)
    assert json.loads(response["body"]) == {"vertices": 2, "edges": 1}


def test_merge_post_tags_points_with_their_carrier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each merged point carries the carrier id taken from its source path."""
    module = load_handler("carriers/merge", monkeypatch)
    objects = _merge_objects()
    with patch("boto3.client", return_value=fake_s3(objects, keys=[*objects])):
        module.lambda_handler({"httpMethod": "POST"}, None)
    merged = json.loads(objects["carriers/merge/vertices.json"])
    assert {row["carrier"] for row in merged} == {"a", "b"}


def test_merge_post_stores_the_substrate(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST writes the merged substrate's vertices and edges back to the store."""
    objects: dict[str, bytes] = {}
    module = load_handler("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3(objects, keys=[])):
        module.lambda_handler({"httpMethod": "POST"}, None)
    assert "carriers/merge/vertices.json" in objects and "carriers/merge/edges.json" in objects


def test_merge_get_serves_vertices(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET vertices returns the stored substrate's vertices."""
    module = load_handler("carriers/merge", monkeypatch)
    stored = json.dumps([{"id": "P"}]).encode()
    with patch("boto3.client", return_value=fake_s3({"carriers/merge/vertices.json": stored})):
        response = module.lambda_handler({"path": "/x/carriers/merge/vertices"}, None)
    assert json.loads(response["body"]) == [{"id": "P"}]


def test_merge_get_404_for_an_unknown_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A merge sub-resource other than vertices/edges is a 404."""
    module = load_handler("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({})):
        response = module.lambda_handler({"path": "/x/carriers/merge/bogus"}, None)
    assert response["statusCode"] == 404


def test_merge_get_404_when_not_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reading the substrate before any merge returns a 'not built' 404."""
    module = load_handler("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({})):
        response = module.lambda_handler({"path": "/x/carriers/merge/edges"}, None)
    assert response["statusCode"] == 404


def test_merge_caches_the_s3_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """A POST then a GET reuse the one cached client."""
    module = load_handler("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({}, keys=[])) as mock_client:
        module.lambda_handler({"httpMethod": "POST"}, None)
        module.lambda_handler({"path": "/x/carriers/merge/vertices"}, None)
    assert mock_client.call_count == 1
