"""Unit tests for the data-centers/merge endpoint Lambda handler.

Merge is its own resource: POST unions every provider's facilities into one site set,
GET serves the stored union. Facilities carry no fiber, so the union is a single
collection served straight off ``/data-centers/merge``. None of this is shared, so it
lives here.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from test_handler_contracts import load_handler
from test_s3_store_mock import fake_s3


def _merge_objects() -> dict[str, bytes]:
    """Two providers' facility files (one row each), plus a non-vertices file to skip."""
    return {
        "data-centers/equinix/vertices.json": json.dumps([{"municipality": "X"}]).encode(),
        "data-centers/equinix/notes.json": json.dumps([{"municipality": "Z"}]).encode(),
        "data-centers/flexential/vertices.json": json.dumps([{"municipality": "Y"}]).encode(),
    }


def test_merge_post_unions_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST counts the facilities unioned (skipping the merge's own output and non-vertices)."""
    module = load_handler("data-centers/merge", monkeypatch)
    objects = _merge_objects()
    fake = fake_s3(objects, keys=[*objects, "data-centers/merge/vertices.json"])
    with patch("boto3.client", return_value=fake):
        response = module.lambda_handler({"httpMethod": "POST"}, None)
    assert json.loads(response["body"]) == {"vertices": 2}


def test_merge_post_tags_facilities_with_their_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each merged facility carries the provider id taken from its source path."""
    module = load_handler("data-centers/merge", monkeypatch)
    objects = _merge_objects()
    with patch("boto3.client", return_value=fake_s3(objects, keys=[*objects])):
        module.lambda_handler({"httpMethod": "POST"}, None)
    merged = json.loads(objects["data-centers/merge/vertices.json"])
    assert {row["provider"] for row in merged} == {"equinix", "flexential"}


def test_merge_post_skips_its_own_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST never folds the merge's own vertices file back into the union."""
    module = load_handler("data-centers/merge", monkeypatch)
    objects = {"data-centers/merge/vertices.json": json.dumps([{"provider": "stale"}]).encode()}
    with patch("boto3.client", return_value=fake_s3(objects, keys=[*objects])):
        module.lambda_handler({"httpMethod": "POST"}, None)
    assert json.loads(objects["data-centers/merge/vertices.json"]) == []


def test_merge_post_stores_the_union(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST writes the merged union back to the store."""
    objects: dict[str, bytes] = {}
    module = load_handler("data-centers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3(objects, keys=[])):
        module.lambda_handler({"httpMethod": "POST"}, None)
    assert "data-centers/merge/vertices.json" in objects


def test_merge_get_serves_the_union(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET on the merge resource returns the stored union."""
    module = load_handler("data-centers/merge", monkeypatch)
    stored = json.dumps([{"provider": "equinix"}]).encode()
    with patch("boto3.client",
               return_value=fake_s3({"data-centers/merge/vertices.json": stored})):
        response = module.lambda_handler({"path": "/x/data-centers/merge"}, None)
    assert json.loads(response["body"]) == [{"provider": "equinix"}]


def test_merge_get_404_for_a_deeper_sub_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """A path deeper than the merge resource is not a resource here and is a 404."""
    module = load_handler("data-centers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({})):
        response = module.lambda_handler({"path": "/x/data-centers/merge/bogus"}, None)
    assert response["statusCode"] == 404


def test_merge_get_404_when_not_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reading the union before any merge returns a 'not built' 404."""
    module = load_handler("data-centers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({})):
        response = module.lambda_handler({"path": "/x/data-centers/merge"}, None)
    assert response["statusCode"] == 404


def test_merge_caches_the_s3_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """A POST then a GET reuse the one cached client."""
    module = load_handler("data-centers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({}, keys=[])) as mock_client:
        module.lambda_handler({"httpMethod": "POST"}, None)
        module.lambda_handler({"path": "/x/data-centers/merge"}, None)
    assert mock_client.call_count == 1
