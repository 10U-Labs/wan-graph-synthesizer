"""Layer 1 (existence): the data-centers stack's resources exist in AWS."""
from __future__ import annotations

from typing import Any

from test_fixtures.aws import get_log_group_info


def test_lambda_function_exists(lambda_config: dict[str, Any], function_name: str) -> None:
    """The data-centers handler Lambda exists under its deterministic name."""
    assert lambda_config["FunctionName"] == function_name


def test_iam_role_exists(iam_client: Any, role_name: str) -> None:
    """The Lambda execution role exists."""
    role = iam_client.get_role(RoleName=role_name)
    assert role["Role"]["RoleName"] == role_name


def test_log_group_exists(logs_client: Any, function_name: str) -> None:
    """The handler's CloudWatch log group exists."""
    info = get_log_group_info(logs_client, f"/aws/lambda/{function_name}")
    assert info["exists"]
