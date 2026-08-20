"""Unit tests for the carriers/merge endpoint Lambda handler.

Merge is its own resource: POST unions every carrier's points and fiber segments into
the substrate, GET serves the stored substrate. None of this is shared, so it lives here.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from test_handler_contracts import load_handler
from test_s3_store_mock import fake_s3


def _merge_objects() -> dict[str, bytes]:
    """Two carriers' point and segment files: 2 points and 1 fiber segment in total."""
    return {
        "carriers/a/pops.json": json.dumps([{"municipality": "X"}]).encode(),
        "carriers/a/fiber-segments.json": json.dumps([{"a_municipality": "X"}]).encode(),
        "carriers/b/pops.json": json.dumps([{"municipality": "Y"}]).encode(),
    }


def test_merge_post_unions_carriers(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST counts the points and fiber segments unioned (and skips the merge's own output)."""
    module = load_handler("carriers/merge", monkeypatch)
    objects = _merge_objects()
    fake = fake_s3(objects, keys=[*objects, "carriers/merge/pops.json"])
    with patch("boto3.client", return_value=fake):
        response = module.lambda_handler({"httpMethod": "POST"}, None)
    assert json.loads(response["body"]) == {"pops": 2, "fiber-segments": 1}


def test_merge_post_ignores_a_file_that_is_neither_collection(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A carrier file under an unknown name is left out rather than merged as fiber.

    A rename leaves the store holding the old file beside the new one. Counted as fiber it
    would reach the synthesizer without the columns a segment carries, and every tenant's
    build would fail on the first one it read.
    """
    module = load_handler("carriers/merge", monkeypatch)
    objects = _merge_objects()
    objects["carriers/a/edges.json"] = json.dumps([{"stale": True}]).encode()
    with patch("boto3.client", return_value=fake_s3(objects, keys=[*objects])):
        response = module.lambda_handler({"httpMethod": "POST"}, None)
    assert json.loads(response["body"]) == {"pops": 2, "fiber-segments": 1}


def test_merge_post_tags_points_with_their_carrier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each merged point carries the carrier id taken from its source path."""
    module = load_handler("carriers/merge", monkeypatch)
    objects = _merge_objects()
    with patch("boto3.client", return_value=fake_s3(objects, keys=[*objects])):
        module.lambda_handler({"httpMethod": "POST"}, None)
    merged = json.loads(objects["carriers/merge/pops.json"])
    assert {row["carrier"] for row in merged} == {"a", "b"}


def test_merge_post_stores_the_substrate(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST writes the merged substrate's sites and links back to the store."""
    objects: dict[str, bytes] = {}
    module = load_handler("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3(objects, keys=[])):
        module.lambda_handler({"httpMethod": "POST"}, None)
    assert "carriers/merge/pops.json" in objects and "carriers/merge/fiber-segments.json" in objects


def test_merge_get_serves_pops(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET sites returns the stored substrate's sites."""
    module = load_handler("carriers/merge", monkeypatch)
    stored = json.dumps([{"id": "P"}]).encode()
    with patch("boto3.client", return_value=fake_s3({"carriers/merge/pops.json": stored})):
        response = module.lambda_handler({"path": "/x/carriers/merge/pops"}, None)
    assert json.loads(response["body"]) == [{"id": "P"}]


def test_merge_get_404_for_an_unknown_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A merge sub-resource other than sites/links is a 404."""
    module = load_handler("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({})):
        response = module.lambda_handler({"path": "/x/carriers/merge/bogus"}, None)
    assert response["statusCode"] == 404


def test_merge_get_404_when_not_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reading the substrate before any merge returns a 'not built' 404."""
    module = load_handler("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({})):
        response = module.lambda_handler({"path": "/x/carriers/merge/fiber-segments"}, None)
    assert response["statusCode"] == 404


def test_merge_caches_the_s3_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """A POST then a GET reuse the one cached client."""
    module = load_handler("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({}, keys=[])) as mock_client:
        module.lambda_handler({"httpMethod": "POST"}, None)
        module.lambda_handler({"path": "/x/carriers/merge/pops"}, None)
    assert mock_client.call_count == 1
