"""Unit tests for the csps endpoint stack's declared infrastructure.

Parse the stack's ``.tf`` with hcl2 and assert the Lambda, its log group, and its
IAM role are declared as intended. No AWS calls, no apply. (The handler's runtime
behaviour is covered by ``test_handler.py`` alongside this file.)
"""
from __future__ import annotations

from typing import Any

import pytest

from test_terraform_config import find_resource


def _resource(doc: dict[str, object], resource_type: str, name: str) -> dict[str, Any]:
    """Return the body of a named resource of the given type, or fail."""
    body = find_resource(doc, resource_type, name)
    if body is None:
        raise AssertionError(f"{resource_type}.{name} is not declared")
    return body


def test_lambda_runtime_is_python313(csps_main: dict[str, object]) -> None:
    """The handler Lambda runs on Python 3.13."""
    handler = _resource(csps_main, "aws_lambda_function", "handler")
    assert handler["runtime"] == "python3.13"


def test_lambda_is_arm64(csps_main: dict[str, object]) -> None:
    """The handler Lambda runs on ARM64 (Graviton)."""
    handler = _resource(csps_main, "aws_lambda_function", "handler")
    assert handler["architectures"] == ["arm64"]


def test_lambda_entrypoint(csps_main: dict[str, object]) -> None:
    """The handler Lambda invokes ``handler.lambda_handler``."""
    handler = _resource(csps_main, "aws_lambda_function", "handler")
    assert handler["handler"] == "handler.lambda_handler"


@pytest.mark.parametrize("variable", ["STORE_BUCKET", "WAN_FUNCTION"])
def test_lambda_environment_declares_variable(
        csps_main: dict[str, object], variable: str) -> None:
    """The handler Lambda is given each environment variable it reads."""
    handler = _resource(csps_main, "aws_lambda_function", "handler")
    assert variable in handler["environment"][0]["variables"]


def test_log_group_retention_is_seven_days(csps_main: dict[str, object]) -> None:
    """The handler's log group retains events for seven days."""
    log_group = _resource(csps_main, "aws_cloudwatch_log_group", "handler")
    assert log_group["retention_in_days"] == 7


def test_iam_role_is_declared(csps_iam: dict[str, object]) -> None:
    """The Lambda execution role is declared."""
    assert find_resource(csps_iam, "aws_iam_role", "lambda") is not None


def test_store_access_policy_is_declared(csps_iam: dict[str, object]) -> None:
    """The store-access inline policy is declared on the role."""
    assert find_resource(csps_iam, "aws_iam_role_policy", "store_access") is not None


def test_api_gateway_invoke_permission_is_declared(
        csps_main: dict[str, object]) -> None:
    """API Gateway is granted permission to invoke the handler."""
    assert find_resource(csps_main, "aws_lambda_permission", "api_gateway") is not None
