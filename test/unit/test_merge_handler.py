"""Unit tests for the carrier merge Lambda handler."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from module_utils import create_lambda_loader
from repo_utils import REPO_ROOT
from s3_store_mock import fake_s3

_LAMBDAS = REPO_ROOT / "src" / "api" / "endpoints" / "merge" / "lambdas"
_load = create_lambda_loader(_LAMBDAS)


@pytest.fixture(name="handler")
def handler_fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the merge handler with a test bucket configured."""
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    module: Any = _load("handler.py", "merge_handler")
    module.clear_clients()
    return module


def _carrier_bytes() -> bytes:
    """A stored carrier graph (one PoP, no edges) as JSON bytes."""
    return json.dumps({"vertices": [{"id": "P"}], "edges": []}).encode()


def test_post_unions_carriers_into_the_substrate(handler: Any) -> None:
    """POST counts the vertices unioned from every carrier (skipping non-JSON keys)."""
    objects = {"carriers/lumen.json": _carrier_bytes(), "carriers/zayo.json": _carrier_bytes()}
    fake = fake_s3(objects, keys=[*objects, "carriers/_notes.txt"])
    with patch("boto3.client", return_value=fake):
        response = handler.lambda_handler({"httpMethod": "POST"}, None)
    assert json.loads(response["body"]) == {"vertices": 2, "edges": 0}


def test_post_stores_the_substrate(handler: Any) -> None:
    """POST writes the merged substrate back to the store."""
    objects: dict[str, bytes] = {}
    with patch("boto3.client", return_value=fake_s3(objects, keys=[])):
        handler.lambda_handler({"httpMethod": "POST"}, None)
    assert "merge/substrate.json" in objects


def test_get_serves_the_substrate_vertices(handler: Any) -> None:
    """GET vertices returns the stored substrate's vertices."""
    stored = json.dumps({"vertices": [{"id": "P"}], "edges": []}).encode()
    fake = fake_s3({"merge/substrate.json": stored})
    with patch("boto3.client", return_value=fake):
        response = handler.lambda_handler({"path": "/x/carriers/merge/vertices"}, None)
    assert json.loads(response["body"]) == [{"id": "P"}]


def test_get_404_for_an_unknown_collection(handler: Any) -> None:
    """A merge sub-resource other than vertices/edges is a 404."""
    with patch("boto3.client", return_value=fake_s3({})):
        response = handler.lambda_handler({"path": "/x/carriers/merge/bogus"}, None)
    assert response["statusCode"] == 404


def test_get_404_when_the_substrate_is_not_built(handler: Any) -> None:
    """Reading the substrate before any merge returns a 'not built' 404."""
    with patch("boto3.client", return_value=fake_s3({})):
        response = handler.lambda_handler({"path": "/x/carriers/merge/edges"}, None)
    assert response["statusCode"] == 404


def test_caches_the_s3_client(handler: Any) -> None:
    """A POST then a GET reuse the one cached client."""
    with patch("boto3.client", return_value=fake_s3({}, keys=[])) as mock_client:
        handler.lambda_handler({"httpMethod": "POST"}, None)
        handler.lambda_handler({"path": "/x/carriers/merge/vertices"}, None)
    assert mock_client.call_count == 1
