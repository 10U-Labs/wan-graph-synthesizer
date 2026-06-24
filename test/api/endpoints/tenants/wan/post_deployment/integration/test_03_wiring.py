"""Layer 3 (wiring): the live wan resources are connected to each other.

These verify the connections that existence and configuration cannot: the Lambda
assumes the declared role, API Gateway and EventBridge are allowed to invoke it,
the recovery rule targets the Lambda, and the dispatch role can launch the task.
"""
from __future__ import annotations

from typing import Any


def test_lambda_assumes_the_declared_role(
        lambda_config: dict[str, Any], role_name: str) -> None:
    """The live Lambda runs as the declared execution role."""
    assert lambda_config["Role"].endswith(f"role/{role_name}")


def test_api_gateway_may_invoke_the_lambda(lambda_client: Any, function_name: str) -> None:
    """API Gateway holds permission to invoke the live Lambda."""
    policy = lambda_client.get_policy(FunctionName=function_name)["Policy"]
    assert "apigateway.amazonaws.com" in policy


def test_eventbridge_may_invoke_the_lambda(lambda_client: Any, function_name: str) -> None:
    """EventBridge holds permission to invoke the live Lambda."""
    policy = lambda_client.get_policy(FunctionName=function_name)["Policy"]
    assert "events.amazonaws.com" in policy


def test_recovery_rule_targets_the_lambda(events_client: Any, function_name: str) -> None:
    """The Spot-recovery rule's target is the dispatching Lambda."""
    targets = events_client.list_targets_by_rule(Rule="wan-graph-synthesizer-task-stopped")
    assert targets["Targets"][0]["Arn"].endswith(function_name)


def test_dispatch_role_grants_run_task(iam_client: Any, role_name: str) -> None:
    """The dispatch role policy grants the Lambda ``ecs:RunTask``."""
    policy = iam_client.get_role_policy(RoleName=role_name, PolicyName="Dispatch")
    assert "ecs:RunTask" in str(policy["PolicyDocument"])
