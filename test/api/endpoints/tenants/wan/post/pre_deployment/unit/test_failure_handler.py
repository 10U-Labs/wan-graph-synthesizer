from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from repo_utils import REPO_ROOT
from test_module_utils import load_module_from_path
from test_s3_store_mock import fake_s3

_PATH = REPO_ROOT / "src/api/endpoints/tenants/wan/post/lambdas/synthesizer/failure_handler.py"


@pytest.fixture(name="failure_handler")
def failure_handler_fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    return load_module_from_path("failure_handler", _PATH)


def _event(tenant: str = "f-35", condition: str | None = "RetriesExhausted") -> dict[str, Any]:
    context = {"condition": condition} if condition is not None else {}
    return {"requestPayload": {"tenant": tenant}, "requestContext": context}


def _run(module: Any, event: dict[str, Any]) -> dict[str, bytes]:
    objects: dict[str, bytes] = {}
    with patch("boto3.client", return_value=fake_s3(objects)):
        module.lambda_handler(event, None)
    return objects


def test_records_the_timeout_status(failure_handler: Any) -> None:
    objects = _run(failure_handler, _event())
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "timeout"


def test_records_timeout_when_aws_reports_no_condition(failure_handler: Any) -> None:
    objects = _run(failure_handler, _event(condition=None))
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "timeout"


def test_writes_to_the_wan_status_key(failure_handler: Any) -> None:
    objects = _run(failure_handler, _event())
    assert "tenants/f-35/wan-status.json" in objects


def test_reads_the_tenant_from_the_request_payload(failure_handler: Any) -> None:
    objects = _run(failure_handler, _event(tenant="dow"))
    assert "tenants/dow/wan-status.json" in objects


def test_reason_names_the_failure_condition(failure_handler: Any) -> None:
    objects = _run(failure_handler, _event(condition="RetriesExhausted"))
    assert "RetriesExhausted" in json.loads(objects["tenants/f-35/wan-status.json"])["reason"]


def test_reason_defaults_when_no_condition(failure_handler: Any) -> None:
    objects = _run(failure_handler, _event(condition=None))
    assert "timed out or crashed" in json.loads(objects["tenants/f-35/wan-status.json"])["reason"]
