"""Unit tests for the tenants/wan endpoint Lambda handler (the dispatcher).

A POST records a ``creating`` status and async-invokes the synthesizer worker Lambda;
a GET reports the tenant's WAN status from the store. All of this is endpoint-specific.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from test_handler_contracts import load_handler, write_clients


def _wan(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the wan dispatcher with the worker function name configured."""
    return load_handler(
        "tenants/wan",
        monkeypatch,
        subdir="endpoint",
        WORKER_FUNCTION_NAME="wan-graph-synthesizer-wan-worker",
    )


def test_wan_post_returns_202(monkeypatch: pytest.MonkeyPatch) -> None:
    """Starting a create acknowledges with 202."""
    module = _wan(monkeypatch)
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler(event, None)
    assert response["statusCode"] == 202


def test_wan_post_invokes_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """A create asynchronously invokes the synthesizer worker exactly once."""
    module = _wan(monkeypatch)
    invocations: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients({}, invocations)):
        module.lambda_handler(event, None)
    assert len(invocations) == 1


def test_wan_post_invokes_the_named_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """The invoke targets the worker function named in the environment."""
    module = _wan(monkeypatch)
    invocations: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients({}, invocations)):
        module.lambda_handler(event, None)
    assert invocations[0]["FunctionName"] == "wan-graph-synthesizer-wan-worker"


def test_wan_post_invokes_the_worker_asynchronously(monkeypatch: pytest.MonkeyPatch) -> None:
    """The worker is invoked with the Event (async) invocation type."""
    module = _wan(monkeypatch)
    invocations: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients({}, invocations)):
        module.lambda_handler(event, None)
    assert invocations[0]["InvocationType"] == "Event"


def test_wan_post_passes_the_tenant_to_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """The invoke payload carries the tenant the worker should build."""
    module = _wan(monkeypatch)
    invocations: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients({}, invocations)):
        module.lambda_handler(event, None)
    assert json.loads(invocations[0]["Payload"]) == {"tenant": "f-35"}


def test_wan_post_marks_status_creating(monkeypatch: pytest.MonkeyPatch) -> None:
    """A create records a 'creating' status marker in the store."""
    module = _wan(monkeypatch)
    objects: dict[str, bytes] = {}
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(event, None)
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "creating"


def test_wan_get_404_before_any_create(monkeypatch: pytest.MonkeyPatch) -> None:
    """A WAN status read before any create is a 404."""
    module = _wan(monkeypatch)
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler({"pathParameters": {"tenant": "f-35"}}, None)
    assert response["statusCode"] == 404


def test_wan_get_200_while_creating(monkeypatch: pytest.MonkeyPatch) -> None:
    """A WAN still being created reports 200 with its status."""
    module = _wan(monkeypatch)
    objects = {"tenants/f-35/wan-status.json": json.dumps({"status": "creating"}).encode()}
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        response = module.lambda_handler({"pathParameters": {"tenant": "f-35"}}, None)
    assert response["statusCode"] == 200


def test_wan_get_422_when_no_valid_wan(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed create reports 422 (no valid WAN was possible)."""
    module = _wan(monkeypatch)
    objects = {"tenants/f-35/wan-status.json": json.dumps({"status": "failed"}).encode()}
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        response = module.lambda_handler({"pathParameters": {"tenant": "f-35"}}, None)
    assert response["statusCode"] == 422


def test_wan_404_when_no_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """A request without a tenant path parameter is a 404."""
    module = _wan(monkeypatch)
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler({}, None)
    assert response["statusCode"] == 404


def test_wan_caches_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two creates build the S3 and Lambda clients once each, then reuse them."""
    module = _wan(monkeypatch)
    post = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients({}, [])) as mock_client:
        module.lambda_handler(post, None)
        module.lambda_handler(post, None)
    assert mock_client.call_count == 2
