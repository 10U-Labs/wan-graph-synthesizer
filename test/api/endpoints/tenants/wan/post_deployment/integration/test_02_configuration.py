"""Layer 2 (configuration): the live wan resources match their declaration."""
from __future__ import annotations

from typing import Any

import pytest


def test_runtime_is_python313(lambda_config: dict[str, Any]) -> None:
    """The live Lambda runs on Python 3.13."""
    assert lambda_config["Runtime"] == "python3.13"


def test_is_arm64(lambda_config: dict[str, Any]) -> None:
    """The live Lambda runs on ARM64."""
    assert "arm64" in lambda_config["Architectures"]


def test_timeout_is_ten_seconds(lambda_config: dict[str, Any]) -> None:
    """The live Lambda's timeout matches the declaration."""
    assert lambda_config["Timeout"] == 10


def test_memory_is_128mb(lambda_config: dict[str, Any]) -> None:
    """The live Lambda's memory matches the declaration."""
    assert lambda_config["MemorySize"] == 128


def test_entrypoint(lambda_config: dict[str, Any]) -> None:
    """The live Lambda invokes ``handler.lambda_handler``."""
    assert lambda_config["Handler"] == "handler.lambda_handler"


@pytest.mark.parametrize(
    "variable",
    ["STORE_BUCKET", "CLUSTER_ARN", "TASK_DEFINITION_ARN", "SUBNET_ID", "SECURITY_GROUP_ID"],
)
def test_environment_variable_is_set(lambda_config: dict[str, Any], variable: str) -> None:
    """The live Lambda carries each environment variable it reads."""
    assert variable in lambda_config["Environment"]["Variables"]


def test_task_definition_is_fargate(task_definition: dict[str, Any]) -> None:
    """The live task definition is FARGATE-compatible."""
    assert "FARGATE" in task_definition["requiresCompatibilities"]


def test_task_definition_cpu(task_definition: dict[str, Any]) -> None:
    """The live task definition reserves 8192 CPU units."""
    assert task_definition["cpu"] == "8192"


def test_task_definition_memory(task_definition: dict[str, Any]) -> None:
    """The live task definition reserves 32768 MB of memory."""
    assert task_definition["memory"] == "32768"


def test_task_stopped_rule_is_enabled(events_client: Any) -> None:
    """The live Spot-recovery rule is enabled."""
    rule = events_client.describe_rule(Name="wan-graph-synthesizer-task-stopped")
    assert rule["State"] == "ENABLED"
