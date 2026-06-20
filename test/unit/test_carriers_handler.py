"""Unit tests for the carriers read Lambda handler."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from module_utils import create_lambda_loader
from repo_utils import REPO_ROOT
from s3_store_mock import fake_s3

_LAMBDAS = REPO_ROOT / "src" / "api" / "endpoints" / "carriers" / "lambdas"
_load = create_lambda_loader(_LAMBDAS)


@pytest.fixture(name="handler")
def handler_fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the carriers handler with a test bucket configured."""
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    module: Any = _load("handler.py", "carriers_handler")
    module.clear_clients()
    return module


def _graph_bytes() -> bytes:
    """A stored carrier input graph (vertices + edges) as JSON bytes."""
    return json.dumps({"vertices": [{"id": "P"}], "edges": []}).encode()


def test_lists_the_stored_carriers(handler: Any) -> None:
    """GET /carriers returns the ids of the carriers in the store."""
    fake = fake_s3({}, keys=["carriers/lumen.json", "carriers/zayo.json"])
    with patch("boto3.client", return_value=fake):
        response = handler.lambda_handler({}, None)
    assert json.loads(response["body"]) == ["lumen", "zayo"]


def test_serves_a_carriers_vertices(handler: Any) -> None:
    """A carrier vertices request returns the stored graph's vertices."""
    fake = fake_s3({"carriers/lumen.json": _graph_bytes()})
    event = {"pathParameters": {"carrier": "lumen"}, "path": "/x/carriers/lumen/vertices"}
    with patch("boto3.client", return_value=fake):
        response = handler.lambda_handler(event, None)
    assert response["statusCode"] == 200


def test_returns_404_for_an_unknown_collection(handler: Any) -> None:
    """A known carrier with an unknown collection is a 404."""
    event = {"pathParameters": {"carrier": "lumen"}, "path": "/x/carriers/lumen/bogus"}
    with patch("boto3.client", return_value=fake_s3({})):
        response = handler.lambda_handler(event, None)
    assert response["statusCode"] == 404


def test_returns_404_when_the_carrier_is_not_built(handler: Any) -> None:
    """A carrier whose object is absent returns a 'not built' 404."""
    event = {"pathParameters": {"carrier": "zayo"}, "path": "/x/carriers/zayo/edges"}
    with patch("boto3.client", return_value=fake_s3({})):
        response = handler.lambda_handler(event, None)
    assert response["statusCode"] == 404


def test_caches_the_s3_client(handler: Any) -> None:
    """The second request reuses the cached client rather than rebuilding it."""
    with patch("boto3.client", return_value=fake_s3({}, keys=[])) as mock_client:
        handler.lambda_handler({}, None)
        handler.lambda_handler({}, None)
    assert mock_client.call_count == 1
