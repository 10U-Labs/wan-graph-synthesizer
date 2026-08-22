from __future__ import annotations

from typing import Any


def test_lambda_assumes_the_declared_role(
        lambda_config: dict[str, Any], role_name: str) -> None:
    assert lambda_config["Role"].endswith(f"role/{role_name}")


def test_api_gateway_may_invoke_the_lambda(lambda_client: Any, function_name: str) -> None:
    policy = lambda_client.get_policy(FunctionName=function_name)["Policy"]
    assert "apigateway.amazonaws.com" in policy


def test_role_grants_store_access(iam_client: Any, role_name: str) -> None:
    policy = iam_client.get_role_policy(RoleName=role_name, PolicyName="StoreReadWrite")
    assert "s3:GetObject" in str(policy["PolicyDocument"])
