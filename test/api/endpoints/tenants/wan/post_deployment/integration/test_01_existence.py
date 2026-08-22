from __future__ import annotations

from typing import Any

from test_fixtures.aws import get_log_group_info


def test_lambda_function_exists(lambda_config: dict[str, Any], function_name: str) -> None:
    assert lambda_config["FunctionName"] == function_name


def test_iam_role_exists(iam_client: Any, role_name: str) -> None:
    role = iam_client.get_role(RoleName=role_name)
    assert role["Role"]["RoleName"] == role_name


def test_lambda_log_group_exists(logs_client: Any, function_name: str) -> None:
    info = get_log_group_info(logs_client, f"/aws/lambda/{function_name}")
    assert info["exists"]
