"""Unit tests for the tenants/wan endpoint (dispatcher) stack's declared infrastructure.

Parse the stack's ``.tf`` with hcl2 and assert the dispatching Lambda, its log group
and role are declared as intended. No AWS calls, no apply. (The handler's runtime
behaviour is covered by ``test_handler.py``; the synthesizer Lambda lives in its own
stack, covered by ``synthesizer/pre_deployment/unit/test_stack.py``.)
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


@pytest.mark.parametrize("variable", ["STORE_BUCKET", "SYNTHESIZER_FUNCTION_NAME"])
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
    """The dispatch policy grants ``lambda:InvokeFunction`` to start the synthesizer."""
    dispatch = _resource(wan_iam, "aws_iam_role_policy", "dispatch")
    assert "lambda:InvokeFunction" in str(dispatch["policy"])


def test_api_gateway_invoke_permission_is_declared(wan_lambda: dict[str, object]) -> None:
    """API Gateway is granted permission to invoke the dispatcher."""
    assert find_resource(wan_lambda, "aws_lambda_permission", "api_gateway") is not None
