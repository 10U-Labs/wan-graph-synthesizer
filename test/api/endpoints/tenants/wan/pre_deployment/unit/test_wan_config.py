"""Unit tests for the tenants/wan endpoint stack's declared infrastructure.

Parse the stack's ``.tf`` with hcl2 and assert the dispatching Lambda, its log
group and role, and the synthesizer runtime infra (ECR repo, ECS cluster,
Fargate task definition, EventBridge recovery rule, synthesizer log group) are
declared as intended. No AWS calls, no apply. (The handler's runtime behaviour is
covered by ``test_handler.py`` alongside this file.)
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


@pytest.mark.parametrize(
    "variable",
    ["STORE_BUCKET", "CLUSTER_ARN", "TASK_DEFINITION_ARN", "SUBNET_ID", "SECURITY_GROUP_ID"],
)
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


def test_dispatch_policy_grants_run_task(wan_iam: dict[str, object]) -> None:
    """The dispatch policy grants ``ecs:RunTask`` to launch the create."""
    dispatch = _resource(wan_iam, "aws_iam_role_policy", "dispatch")
    assert "ecs:RunTask" in str(dispatch["policy"])


def test_api_gateway_invoke_permission_is_declared(wan_lambda: dict[str, object]) -> None:
    """API Gateway is granted permission to invoke the dispatcher."""
    assert find_resource(wan_lambda, "aws_lambda_permission", "api_gateway") is not None


def test_eventbridge_invoke_permission_is_declared(
        wan_eventbridge: dict[str, object]) -> None:
    """EventBridge is granted permission to invoke the dispatcher."""
    assert find_resource(wan_eventbridge, "aws_lambda_permission", "eventbridge") is not None


def test_ecr_repository_name(wan_main: dict[str, object]) -> None:
    """The synthesizer ECR repository is named ``wan-graph-synthesizer``."""
    repo = _resource(wan_main, "aws_ecr_repository", "synthesizer")
    assert repo["name"] == "wan-graph-synthesizer"


def test_ecs_cluster_name(wan_main: dict[str, object]) -> None:
    """The synthesizer ECS cluster is named ``wan-graph-synthesizer``."""
    cluster = _resource(wan_main, "aws_ecs_cluster", "this")
    assert cluster["name"] == "wan-graph-synthesizer"


def test_task_definition_family(wan_main: dict[str, object]) -> None:
    """The Fargate task definition family is ``wan-graph-synthesizer``."""
    task = _resource(wan_main, "aws_ecs_task_definition", "synthesizer")
    assert task["family"] == "wan-graph-synthesizer"


def test_task_definition_requires_fargate(wan_main: dict[str, object]) -> None:
    """The task definition requires the FARGATE launch type."""
    task = _resource(wan_main, "aws_ecs_task_definition", "synthesizer")
    assert task["requires_compatibilities"] == ["FARGATE"]


def test_task_definition_cpu(wan_main: dict[str, object]) -> None:
    """The task definition reserves 8192 CPU units."""
    task = _resource(wan_main, "aws_ecs_task_definition", "synthesizer")
    assert task["cpu"] == "8192"


def test_task_definition_memory(wan_main: dict[str, object]) -> None:
    """The task definition reserves 32768 MB of memory."""
    task = _resource(wan_main, "aws_ecs_task_definition", "synthesizer")
    assert task["memory"] == "32768"


def test_synthesizer_log_group_name(wan_main: dict[str, object]) -> None:
    """The synthesizer's CloudWatch log group is ``/ecs/wan-graph-synthesizer``."""
    log_group = _resource(wan_main, "aws_cloudwatch_log_group", "synthesizer")
    assert log_group["name"] == "/ecs/wan-graph-synthesizer"


def test_task_stopped_rule_name(wan_eventbridge: dict[str, object]) -> None:
    """The Spot-recovery rule is named ``wan-graph-synthesizer-task-stopped``."""
    rule = _resource(wan_eventbridge, "aws_cloudwatch_event_rule", "task_stopped")
    assert rule["name"] == "wan-graph-synthesizer-task-stopped"


def test_task_stopped_target_is_the_handler(wan_eventbridge: dict[str, object]) -> None:
    """The recovery rule's target is the dispatching Lambda."""
    target = _resource(wan_eventbridge, "aws_cloudwatch_event_target", "task_stopped_lambda")
    assert "aws_lambda_function.handler.arn" in str(target["arn"])
