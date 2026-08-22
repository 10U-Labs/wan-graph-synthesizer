from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from test_handler_contracts import load_handler
from test_s3_store_mock import fake_s3


def _merge_objects() -> dict[str, bytes]:
    return {
        "carriers/a/pops.json": json.dumps([{"municipality": "X"}]).encode(),
        "carriers/a/fiber-segments.json": json.dumps([{"a_municipality": "X"}]).encode(),
        "carriers/b/pops.json": json.dumps([{"municipality": "Y"}]).encode(),
    }


def test_merge_post_unions_carriers(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_handler("carriers/merge", monkeypatch)
    objects = _merge_objects()
    fake = fake_s3(objects, keys=[*objects, "carriers/merge/pops.json"])
    with patch("boto3.client", return_value=fake):
        response = module.lambda_handler({"httpMethod": "POST"}, None)
    assert json.loads(response["body"]) == {"pops": 2, "fiber-segments": 1}


def test_merge_post_ignores_a_file_that_is_neither_collection(
        monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_handler("carriers/merge", monkeypatch)
    objects = _merge_objects()
    objects["carriers/a/edges.json"] = json.dumps([{"stale": True}]).encode()
    with patch("boto3.client", return_value=fake_s3(objects, keys=[*objects])):
        response = module.lambda_handler({"httpMethod": "POST"}, None)
    assert json.loads(response["body"]) == {"pops": 2, "fiber-segments": 1}


def test_merge_post_tags_points_with_their_carrier(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_handler("carriers/merge", monkeypatch)
    objects = _merge_objects()
    with patch("boto3.client", return_value=fake_s3(objects, keys=[*objects])):
        module.lambda_handler({"httpMethod": "POST"}, None)
    merged = json.loads(objects["carriers/merge/pops.json"])
    assert {row["carrier"] for row in merged} == {"a", "b"}


def test_merge_post_stores_the_merged_carriers(monkeypatch: pytest.MonkeyPatch) -> None:
    objects: dict[str, bytes] = {}
    module = load_handler("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3(objects, keys=[])):
        module.lambda_handler({"httpMethod": "POST"}, None)
    assert "carriers/merge/pops.json" in objects and "carriers/merge/fiber-segments.json" in objects


def test_merge_get_serves_pops(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_handler("carriers/merge", monkeypatch)
    stored = json.dumps([{"id": "P"}]).encode()
    with patch("boto3.client", return_value=fake_s3({"carriers/merge/pops.json": stored})):
        response = module.lambda_handler({"path": "/x/carriers/merge/pops"}, None)
    assert json.loads(response["body"]) == [{"id": "P"}]


def test_merge_get_404_for_an_unknown_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_handler("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({})):
        response = module.lambda_handler({"path": "/x/carriers/merge/bogus"}, None)
    assert response["statusCode"] == 404


def test_merge_get_404_when_not_built(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_handler("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({})):
        response = module.lambda_handler({"path": "/x/carriers/merge/fiber-segments"}, None)
    assert response["statusCode"] == 404


def test_merge_caches_the_s3_client(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_handler("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({}, keys=[])) as mock_client:
        module.lambda_handler({"httpMethod": "POST"}, None)
        module.lambda_handler({"path": "/x/carriers/merge/pops"}, None)
    assert mock_client.call_count == 1
