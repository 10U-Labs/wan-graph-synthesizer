"""Unit tests for the tenants/wan endpoint stack's declared infrastructure.

Parse the stack's ``.tf`` with hcl2 and assert the dispatching Lambda, its log group
and role, and the synthesizer worker Lambda (its runtime, size, handler, role and S3
access) are declared as intended. No AWS calls, no apply. (The handlers' runtime
behaviour is covered by ``test_handler.py`` and the worker's unit tests.)
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


def test_lambda_runtime_is_python313(wan_lambda: dict[str, object]) -> None:
    """The dispatching Lambda runs on Python 3.13."""
    handler = _resource(wan_lambda, "aws_lambda_function", "handler")
    assert handler["runtime"] == "python3.13"


def test_lambda_is_arm64(wan_lambda: dict[str, object]) -> None:
    """The dispatching Lambda runs on ARM64 (Graviton)."""
    handler = _resource(wan_lambda, "aws_lambda_function", "handler")
    assert handler["architectures"] == ["arm64"]


def test_lambda_timeout(wan_lambda: dict[str, object]) -> None:
    """The dispatching Lambda's timeout is ten seconds."""
    handler = _resource(wan_lambda, "aws_lambda_function", "handler")
    assert handler["timeout"] == 10


def test_lambda_memory(wan_lambda: dict[str, object]) -> None:
    """The dispatching Lambda is sized at 128 MB."""
    handler = _resource(wan_lambda, "aws_lambda_function", "handler")
    assert handler["memory_size"] == 128


def test_lambda_entrypoint(wan_lambda: dict[str, object]) -> None:
    """The dispatching Lambda invokes ``handler.lambda_handler``."""
    handler = _resource(wan_lambda, "aws_lambda_function", "handler")
    assert handler["handler"] == "handler.lambda_handler"


@pytest.mark.parametrize("variable", ["STORE_BUCKET", "WORKER_FUNCTION_NAME"])
def test_lambda_environment_declares_variable(
        wan_lambda: dict[str, object], variable: str) -> None:
    """The dispatching Lambda is given each environment variable it reads."""
    handler = _resource(wan_lambda, "aws_lambda_function", "handler")
    assert variable in handler["environment"][0]["variables"]


def test_log_group_retention_is_seven_days(wan_lambda: dict[str, object]) -> None:
    """The dispatching Lambda's log group retains events for seven days."""
    log_group = _resource(wan_lambda, "aws_cloudwatch_log_group", "handler")
    assert log_group["retention_in_days"] == 7


def test_iam_role_is_declared(wan_iam: dict[str, object]) -> None:
    """The Lambda execution role is declared."""
    assert find_resource(wan_iam, "aws_iam_role", "lambda") is not None


def test_dispatch_policy_is_named(wan_iam: dict[str, object]) -> None:
    """The dispatch inline policy is named ``Dispatch``."""
    dispatch = _resource(wan_iam, "aws_iam_role_policy", "dispatch")
    assert dispatch["name"] == "Dispatch"


def test_dispatch_policy_grants_invoke(wan_iam: dict[str, object]) -> None:
    """The dispatch policy grants ``lambda:InvokeFunction`` to start the worker."""
    dispatch = _resource(wan_iam, "aws_iam_role_policy", "dispatch")
    assert "lambda:InvokeFunction" in str(dispatch["policy"])


def test_api_gateway_invoke_permission_is_declared(wan_lambda: dict[str, object]) -> None:
    """API Gateway is granted permission to invoke the dispatcher."""
    assert find_resource(wan_lambda, "aws_lambda_permission", "api_gateway") is not None


def test_worker_runtime_is_python313(wan_main: dict[str, object]) -> None:
    """The synthesizer worker Lambda runs on Python 3.13."""
    worker = _resource(wan_main, "aws_lambda_function", "worker")
    assert worker["runtime"] == "python3.13"


def test_worker_is_arm64(wan_main: dict[str, object]) -> None:
    """The synthesizer worker Lambda runs on ARM64 (Graviton)."""
    worker = _resource(wan_main, "aws_lambda_function", "worker")
    assert worker["architectures"] == ["arm64"]


def test_worker_handler(wan_main: dict[str, object]) -> None:
    """The worker invokes ``synthesizer.handler.lambda_handler``."""
    worker = _resource(wan_main, "aws_lambda_function", "worker")
    assert worker["handler"] == "synthesizer.handler.lambda_handler"


def test_worker_memory_matches_the_old_fargate_size(wan_main: dict[str, object]) -> None:
    """The worker reserves 8192 MB so ``enumeration_limit`` matches the prior 8 GB task."""
    worker = _resource(wan_main, "aws_lambda_function", "worker")
    assert worker["memory_size"] == 8192


def test_worker_timeout_is_the_lambda_maximum(wan_main: dict[str, object]) -> None:
    """The worker's timeout is 900s (the Lambda maximum) -- ample over a ~5s build."""
    worker = _resource(wan_main, "aws_lambda_function", "worker")
    assert worker["timeout"] == 900


def test_worker_carries_the_store_bucket(wan_main: dict[str, object]) -> None:
    """The worker is given the STORE_BUCKET it reads inputs from and writes the WAN to."""
    worker = _resource(wan_main, "aws_lambda_function", "worker")
    assert "STORE_BUCKET" in worker["environment"][0]["variables"]


def test_worker_role_is_declared(wan_main: dict[str, object]) -> None:
    """The worker's own execution role is declared."""
    assert find_resource(wan_main, "aws_iam_role", "worker") is not None


def test_worker_role_grants_store_access(wan_main: dict[str, object]) -> None:
    """The worker role can read inputs and write the WAN to the store."""
    policy = _resource(wan_main, "aws_iam_role_policy", "worker_s3")
    assert "s3:PutObject" in str(policy["policy"])


def test_worker_log_group_retention(wan_main: dict[str, object]) -> None:
    """The worker's log group retains events for fourteen days."""
    log_group = _resource(wan_main, "aws_cloudwatch_log_group", "worker")
    assert log_group["retention_in_days"] == 14
