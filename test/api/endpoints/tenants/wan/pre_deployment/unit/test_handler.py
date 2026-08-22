from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from test_handler_contracts import load_handler, write_clients


def _wan(monkeypatch: pytest.MonkeyPatch) -> Any:
    return load_handler(
        "tenants/wan",
        monkeypatch,
        SYNTHESIZER_FUNCTION_NAME="wan-synthesizer-wan-synthesizer",
    )


def test_wan_post_returns_202(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _wan(monkeypatch)
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler(event, None)
    assert response["statusCode"] == 202


def test_wan_post_invokes_the_synthesizer(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _wan(monkeypatch)
    invocations: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients({}, invocations)):
        module.lambda_handler(event, None)
    assert len(invocations) == 1


def test_wan_post_invokes_the_named_synthesizer(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _wan(monkeypatch)
    invocations: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients({}, invocations)):
        module.lambda_handler(event, None)
    assert invocations[0]["FunctionName"] == "wan-synthesizer-wan-synthesizer"


def test_wan_post_invokes_the_synthesizer_asynchronously(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _wan(monkeypatch)
    invocations: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients({}, invocations)):
        module.lambda_handler(event, None)
    assert invocations[0]["InvocationType"] == "Event"


def test_wan_post_passes_the_tenant_to_the_synthesizer(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _wan(monkeypatch)
    invocations: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients({}, invocations)):
        module.lambda_handler(event, None)
    assert json.loads(invocations[0]["Payload"]) == {"tenant": "f-35"}


def test_wan_post_marks_status_creating(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _wan(monkeypatch)
    objects: dict[str, bytes] = {}
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(event, None)
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "creating"


def test_wan_get_404_before_any_create(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _wan(monkeypatch)
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler({"pathParameters": {"tenant": "f-35"}}, None)
    assert response["statusCode"] == 404


def test_wan_get_200_while_creating(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _wan(monkeypatch)
    objects = {"tenants/f-35/wan-status.json": json.dumps({"status": "creating"}).encode()}
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        response = module.lambda_handler({"pathParameters": {"tenant": "f-35"}}, None)
    assert response["statusCode"] == 200


def test_wan_get_422_when_no_valid_wan(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _wan(monkeypatch)
    objects = {"tenants/f-35/wan-status.json": json.dumps({"status": "fail"}).encode()}
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        response = module.lambda_handler({"pathParameters": {"tenant": "f-35"}}, None)
    assert response["statusCode"] == 422


def test_wan_get_422_when_the_build_was_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _wan(monkeypatch)
    killed = {"tenants/f-35/wan-status.json": json.dumps({"status": "timeout"}).encode()}
    with patch("boto3.client", side_effect=write_clients(killed, [])):
        response = module.lambda_handler({"pathParameters": {"tenant": "f-35"}}, None)
    assert response["statusCode"] == 422


def test_wan_404_when_no_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _wan(monkeypatch)
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler({}, None)
    assert response["statusCode"] == 404


def test_wan_caches_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _wan(monkeypatch)
    post = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients({}, [])) as mock_client:
        module.lambda_handler(post, None)
        module.lambda_handler(post, None)
    assert mock_client.call_count == 2
