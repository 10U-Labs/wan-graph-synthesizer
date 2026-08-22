from __future__ import annotations

from typing import Any

import pytest

from test_terraform_config import find_resource


def _resource(doc: dict[str, object], resource_type: str, name: str) -> dict[str, Any]:
    body = find_resource(doc, resource_type, name)
    if body is None:
        raise AssertionError(f"{resource_type}.{name} is not declared")
    return body


def test_lambda_runtime_is_python313(providers_main: dict[str, object]) -> None:
    handler = _resource(providers_main, "aws_lambda_function", "handler")
    assert handler["runtime"] == "python3.13"


def test_lambda_is_arm64(providers_main: dict[str, object]) -> None:
    handler = _resource(providers_main, "aws_lambda_function", "handler")
    assert handler["architectures"] == ["arm64"]


def test_lambda_entrypoint(providers_main: dict[str, object]) -> None:
    handler = _resource(providers_main, "aws_lambda_function", "handler")
    assert handler["handler"] == "handler.lambda_handler"


@pytest.mark.parametrize("variable", ["STORE_BUCKET"])
def test_lambda_environment_declares_variable(
        providers_main: dict[str, object], variable: str) -> None:
    handler = _resource(providers_main, "aws_lambda_function", "handler")
    assert variable in handler["environment"][0]["variables"]


def test_log_group_retention_is_seven_days(providers_main: dict[str, object]) -> None:
    log_group = _resource(providers_main, "aws_cloudwatch_log_group", "handler")
    assert log_group["retention_in_days"] == 7


def test_iam_role_is_declared(providers_iam: dict[str, object]) -> None:
    assert find_resource(providers_iam, "aws_iam_role", "lambda") is not None


def test_store_access_policy_is_declared(providers_iam: dict[str, object]) -> None:
    assert find_resource(providers_iam, "aws_iam_role_policy", "store_access") is not None


def test_api_gateway_invoke_permission_is_declared(
        providers_main: dict[str, object]) -> None:
    assert find_resource(providers_main, "aws_lambda_permission", "api_gateway") is not None
