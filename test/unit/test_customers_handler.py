"""Unit tests for the customers read Lambda handler."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from module_utils import create_lambda_loader
from repo_utils import REPO_ROOT
from s3_store_mock import fake_s3

_LAMBDAS = REPO_ROOT / "src" / "api" / "endpoints" / "customers" / "lambdas"
_load = create_lambda_loader(_LAMBDAS)


@pytest.fixture(name="handler")
def handler_fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the customers handler with a test bucket configured."""
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    module: Any = _load("handler.py", "customers_handler")
    module.clear_clients()
    return module


def _wan_bytes() -> bytes:
    """A stored customer WAN pre-shaped into its collections, as JSON bytes."""
    return json.dumps(
        {
            "vertices": [{"id": "P", "tier_role": "core"}],
            "edges": [],
            "core-nodes": [{"id": "P"}],
            "aggregation-points": [],
            "access-nodes": [],
        }
    ).encode()


def test_lists_the_built_customers(handler: Any) -> None:
    """GET /customers returns the ids of customers whose WAN is built."""
    fake = fake_s3({}, keys=["customers/f-35/wan.json", "customers/joint/wan.json"])
    with patch("boto3.client", return_value=fake):
        response = handler.lambda_handler({}, None)
    assert json.loads(response["body"]) == ["f-35", "joint"]


def test_serves_a_customers_core_nodes(handler: Any) -> None:
    """A core-nodes request returns the stored WAN's core tier."""
    fake = fake_s3({"customers/f-35/wan.json": _wan_bytes()})
    event = {"pathParameters": {"customer": "f-35"}, "path": "/x/customers/f-35/core-nodes"}
    with patch("boto3.client", return_value=fake):
        response = handler.lambda_handler(event, None)
    assert json.loads(response["body"]) == [{"id": "P"}]


def test_returns_404_for_an_unknown_collection(handler: Any) -> None:
    """A known customer with an unknown collection is a 404."""
    event = {"pathParameters": {"customer": "f-35"}, "path": "/x/customers/f-35/bogus"}
    with patch("boto3.client", return_value=fake_s3({})):
        response = handler.lambda_handler(event, None)
    assert response["statusCode"] == 404


def test_returns_404_when_the_customer_is_not_built(handler: Any) -> None:
    """A customer whose WAN is absent returns a 'not built' 404."""
    event = {"pathParameters": {"customer": "joint"}, "path": "/x/customers/joint/edges"}
    with patch("boto3.client", return_value=fake_s3({})):
        response = handler.lambda_handler(event, None)
    assert response["statusCode"] == 404


def test_caches_the_s3_client(handler: Any) -> None:
    """The second request reuses the cached client rather than rebuilding it."""
    with patch("boto3.client", return_value=fake_s3({}, keys=[])) as mock_client:
        handler.lambda_handler({}, None)
        handler.lambda_handler({}, None)
    assert mock_client.call_count == 1
