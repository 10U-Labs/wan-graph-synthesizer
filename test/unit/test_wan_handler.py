"""Unit tests for the WAN create Lambda handler."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from module_utils import create_lambda_loader
from repo_utils import REPO_ROOT
from s3_store_mock import fake_ecs, fake_s3

_LAMBDAS = REPO_ROOT / "src" / "api" / "endpoints" / "wan" / "lambdas"
_load = create_lambda_loader(_LAMBDAS)


@pytest.fixture(name="handler")
def handler_fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the WAN handler with the create task's environment configured."""
    for name, value in {
        "STORE_BUCKET": "test-bucket",
        "CLUSTER_ARN": "arn:cluster",
        "TASK_DEFINITION_ARN": "arn:task",
        "SUBNET_ID": "subnet-1",
        "SECURITY_GROUP_ID": "sg-1",
    }.items():
        monkeypatch.setenv(name, value)
    module: Any = _load("handler.py", "wan_handler")
    module.clear_clients()
    return module


def _clients(objects: dict[str, bytes], started: list[dict[str, Any]]) -> Any:
    """A boto3.client side effect handing back the S3 and ECS fakes by service."""
    fakes = {"s3": fake_s3(objects), "ecs": fake_ecs(started)}
    return lambda service, **_kwargs: fakes[service]


def _post(customer: str) -> dict[str, Any]:
    """A WAN-create POST event for a customer."""
    return {"httpMethod": "POST", "pathParameters": {"customer": customer}}


def _get(customer: str) -> dict[str, Any]:
    """A WAN-status GET event for a customer."""
    return {"pathParameters": {"customer": customer}}


def test_post_returns_202(handler: Any) -> None:
    """Starting a create acknowledges with 202."""
    with patch("boto3.client", side_effect=_clients({}, [])):
        response = handler.lambda_handler(_post("f-35"), None)
    assert response["statusCode"] == 202


def test_post_launches_one_fargate_task(handler: Any) -> None:
    """A create launches exactly one optimizer task."""
    started: list[dict[str, Any]] = []
    with patch("boto3.client", side_effect=_clients({}, started)):
        handler.lambda_handler(_post("f-35"), None)
    assert len(started) == 1


def test_post_marks_the_status_creating(handler: Any) -> None:
    """A create records a 'creating' status marker in the store."""
    objects: dict[str, bytes] = {}
    with patch("boto3.client", side_effect=_clients(objects, [])):
        handler.lambda_handler(_post("f-35"), None)
    assert "customers/f-35/wan-status.json" in objects


def test_get_404_before_any_create(handler: Any) -> None:
    """A WAN status read before any create is a 404."""
    with patch("boto3.client", side_effect=_clients({}, [])):
        response = handler.lambda_handler(_get("f-35"), None)
    assert response["statusCode"] == 404


def test_get_200_while_creating(handler: Any) -> None:
    """A WAN still being created reports 200 with its status."""
    marker = json.dumps({"status": "creating"}).encode()
    objects = {"customers/f-35/wan-status.json": marker}
    with patch("boto3.client", side_effect=_clients(objects, [])):
        response = handler.lambda_handler(_get("f-35"), None)
    assert response["statusCode"] == 200


def test_get_422_when_no_valid_wan_exists(handler: Any) -> None:
    """A failed create reports 422 (no valid WAN was possible)."""
    marker = json.dumps({"status": "failed", "reason": "disconnected"}).encode()
    objects = {"customers/f-35/wan-status.json": marker}
    with patch("boto3.client", side_effect=_clients(objects, [])):
        response = handler.lambda_handler(_get("f-35"), None)
    assert response["statusCode"] == 422


def test_404_when_no_customer_is_given(handler: Any) -> None:
    """A request without a customer path parameter is a 404."""
    with patch("boto3.client", side_effect=_clients({}, [])):
        response = handler.lambda_handler({}, None)
    assert response["statusCode"] == 404


def test_caches_clients_across_requests(handler: Any) -> None:
    """A POST then a GET build the S3 and ECS clients once each, not again."""
    with patch("boto3.client", side_effect=_clients({}, [])) as mock_client:
        handler.lambda_handler(_post("f-35"), None)
        handler.lambda_handler(_get("f-35"), None)
    assert mock_client.call_count == 2
