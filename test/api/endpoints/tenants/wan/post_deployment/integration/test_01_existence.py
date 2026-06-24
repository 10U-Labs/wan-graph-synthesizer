"""Layer 1 (existence): the wan stack's resources exist in AWS."""
from __future__ import annotations

from typing import Any

from test_fixtures.aws import get_log_group_info


def test_lambda_function_exists(lambda_config: dict[str, Any], function_name: str) -> None:
    """The wan dispatching Lambda exists under its deterministic name."""
    assert lambda_config["FunctionName"] == function_name


def test_iam_role_exists(iam_client: Any, role_name: str) -> None:
    """The Lambda execution role exists."""
    role = iam_client.get_role(RoleName=role_name)
    assert role["Role"]["RoleName"] == role_name


def test_lambda_log_group_exists(logs_client: Any, function_name: str) -> None:
    """The dispatcher's CloudWatch log group exists."""
    info = get_log_group_info(logs_client, f"/aws/lambda/{function_name}")
    assert info["exists"]


def test_ecr_repository_exists(ecr_client: Any) -> None:
    """The synthesizer ECR repository exists."""
    response = ecr_client.describe_repositories(repositoryNames=["wan-graph-synthesizer"])
    assert response["repositories"][0]["repositoryName"] == "wan-graph-synthesizer"


def test_ecs_cluster_is_active(ecs_client: Any) -> None:
    """The synthesizer ECS cluster exists and is ACTIVE."""
    response = ecs_client.describe_clusters(clusters=["wan-graph-synthesizer"])
    assert response["clusters"][0]["status"] == "ACTIVE"


def test_task_definition_exists(task_definition: dict[str, Any]) -> None:
    """The synthesizer Fargate task definition exists."""
    assert task_definition["family"] == "wan-graph-synthesizer"


def test_task_stopped_rule_exists(events_client: Any) -> None:
    """The Spot-recovery EventBridge rule exists."""
    rule = events_client.describe_rule(Name="wan-graph-synthesizer-task-stopped")
    assert rule["Name"] == "wan-graph-synthesizer-task-stopped"


def test_synthesizer_log_group_exists(logs_client: Any) -> None:
    """The synthesizer's CloudWatch log group exists."""
    info = get_log_group_info(logs_client, "/ecs/wan-graph-synthesizer")
    assert info["exists"]
