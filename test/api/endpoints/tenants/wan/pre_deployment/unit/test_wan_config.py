from __future__ import annotations

from typing import Any

import pytest

from test_terraform_config import find_resource


def _resource(doc: dict[str, object], resource_type: str, name: str) -> dict[str, Any]:
    body = find_resource(doc, resource_type, name)
    if body is None:
        raise AssertionError(f"{resource_type}.{name} is not declared")
    return body


def test_lambda_runtime_is_python313(wan_lambda: dict[str, object]) -> None:
    handler = _resource(wan_lambda, "aws_lambda_function", "handler")
    assert handler["runtime"] == "python3.13"


def test_lambda_is_arm64(wan_lambda: dict[str, object]) -> None:
    handler = _resource(wan_lambda, "aws_lambda_function", "handler")
    assert handler["architectures"] == ["arm64"]


def test_lambda_timeout(wan_lambda: dict[str, object]) -> None:
    handler = _resource(wan_lambda, "aws_lambda_function", "handler")
    assert handler["timeout"] == 10


def test_lambda_memory(wan_lambda: dict[str, object]) -> None:
    handler = _resource(wan_lambda, "aws_lambda_function", "handler")
    assert handler["memory_size"] == 128


def test_lambda_entrypoint(wan_lambda: dict[str, object]) -> None:
    handler = _resource(wan_lambda, "aws_lambda_function", "handler")
    assert handler["handler"] == "handler.lambda_handler"


@pytest.mark.parametrize("variable", ["STORE_BUCKET", "SYNTHESIZER_FUNCTION_NAME"])
def test_lambda_environment_declares_variable(
        wan_lambda: dict[str, object], variable: str) -> None:
    handler = _resource(wan_lambda, "aws_lambda_function", "handler")
    assert variable in handler["environment"][0]["variables"]


def test_log_group_retention_is_seven_days(wan_lambda: dict[str, object]) -> None:
    log_group = _resource(wan_lambda, "aws_cloudwatch_log_group", "handler")
    assert log_group["retention_in_days"] == 7


def test_iam_role_is_declared(wan_iam: dict[str, object]) -> None:
    assert find_resource(wan_iam, "aws_iam_role", "lambda") is not None


def test_dispatch_policy_is_named(wan_iam: dict[str, object]) -> None:
    dispatch = _resource(wan_iam, "aws_iam_role_policy", "dispatch")
    assert dispatch["name"] == "Dispatch"


def test_dispatch_policy_grants_invoke(wan_iam: dict[str, object]) -> None:
    dispatch = _resource(wan_iam, "aws_iam_role_policy", "dispatch")
    assert "lambda:InvokeFunction" in str(dispatch["policy"])


def test_dispatch_policy_grants_listing_the_bucket(wan_iam: dict[str, object]) -> None:
    dispatch = _resource(wan_iam, "aws_iam_role_policy", "dispatch")
    assert "s3:ListBucket" in str(dispatch["policy"])


def test_api_gateway_invoke_permission_is_declared(wan_lambda: dict[str, object]) -> None:
    assert find_resource(wan_lambda, "aws_lambda_permission", "api_gateway") is not None
