"""Layer 1 (existence): the synthesizer stack's resources exist in AWS."""
from __future__ import annotations

from typing import Any

from test_fixtures.aws import get_log_group_info


def test_synthesizer_function_exists(
        synthesizer_config: dict[str, Any], synthesizer_function_name: str) -> None:
    """The synthesizer Lambda exists under its deterministic derived name."""
    assert synthesizer_config["FunctionName"] == synthesizer_function_name


def test_synthesizer_role_exists(iam_client: Any, synthesizer_role_name: str) -> None:
    """The synthesizer's execution role exists."""
    role = iam_client.get_role(RoleName=synthesizer_role_name)
    assert role["Role"]["RoleName"] == synthesizer_role_name


def test_synthesizer_log_group_exists(logs_client: Any, synthesizer_function_name: str) -> None:
    """The synthesizer's CloudWatch log group exists."""
    info = get_log_group_info(logs_client, f"/aws/lambda/{synthesizer_function_name}")
    assert info["exists"]


def test_failure_handler_function_exists(
        failure_handler_config: dict[str, Any], failure_handler_function_name: str) -> None:
    """The failure-handler Lambda exists under its deterministic derived name."""
    assert failure_handler_config["FunctionName"] == failure_handler_function_name


def test_failure_handler_role_exists(iam_client: Any, failure_handler_role_name: str) -> None:
    """The failure handler's execution role exists."""
    role = iam_client.get_role(RoleName=failure_handler_role_name)
    assert role["Role"]["RoleName"] == failure_handler_role_name


def test_failure_handler_log_group_exists(
        logs_client: Any, failure_handler_function_name: str) -> None:
    """The failure handler's CloudWatch log group exists."""
    info = get_log_group_info(logs_client, f"/aws/lambda/{failure_handler_function_name}")
    assert info["exists"]
