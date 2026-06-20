"""Unit tests for the CSPs read Lambda handler."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from module_utils import create_lambda_loader
from repo_utils import REPO_ROOT
from s3_store_mock import fake_s3

_LAMBDAS = REPO_ROOT / "src" / "api" / "endpoints" / "csps" / "lambdas"
_load = create_lambda_loader(_LAMBDAS)


@pytest.fixture(name="handler")
def handler_fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the CSPs handler with a test bucket configured."""
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    module: Any = _load("handler.py", "csps_handler")
    module.clear_clients()
    return module


def _regions_bytes() -> bytes:
    """A stored CSP graph (regions only, no edges) as JSON bytes."""
    return json.dumps({"vertices": [{"id": "us-east"}]}).encode()


def test_lists_the_stored_providers(handler: Any) -> None:
    """GET /csps returns the ids of the providers in the store."""
    fake = fake_s3({}, keys=["csps/aws.json", "csps/azure.json"])
    with patch("boto3.client", return_value=fake):
        response = handler.lambda_handler({}, None)
    assert json.loads(response["body"]) == ["aws", "azure"]


def test_serves_a_providers_regions(handler: Any) -> None:
    """A provider vertices request returns the stored graph's regions."""
    fake = fake_s3({"csps/aws.json": _regions_bytes()})
    event = {"pathParameters": {"provider": "aws"}, "path": "/x/csps/aws/vertices"}
    with patch("boto3.client", return_value=fake):
        response = handler.lambda_handler(event, None)
    assert response["statusCode"] == 200


def test_returns_404_for_a_non_vertices_collection(handler: Any) -> None:
    """A CSP has no edges, so any collection other than vertices is a 404."""
    event = {"pathParameters": {"provider": "aws"}, "path": "/x/csps/aws/edges"}
    with patch("boto3.client", return_value=fake_s3({})):
        response = handler.lambda_handler(event, None)
    assert response["statusCode"] == 404


def test_returns_404_when_the_provider_is_not_built(handler: Any) -> None:
    """A provider whose object is absent returns a 'not built' 404."""
    event = {"pathParameters": {"provider": "oci"}, "path": "/x/csps/oci/vertices"}
    with patch("boto3.client", return_value=fake_s3({})):
        response = handler.lambda_handler(event, None)
    assert response["statusCode"] == 404


def test_caches_the_s3_client(handler: Any) -> None:
    """The second request reuses the cached client rather than rebuilding it."""
    with patch("boto3.client", return_value=fake_s3({}, keys=[])) as mock_client:
        handler.lambda_handler({}, None)
        handler.lambda_handler({}, None)
    assert mock_client.call_count == 1
