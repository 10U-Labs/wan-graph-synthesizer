"""Layer 3 (wiring): the live csps Lambda is connected to its role and gateway.

These verify the connections that existence and configuration cannot: the Lambda
assumes the declared role, API Gateway is allowed to invoke it, and the role
actually grants access to the store.
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


def test_role_grants_store_access(iam_client: Any, role_name: str) -> None:
    """The execution role grants the Lambda read/write access to the store."""
    policy = iam_client.get_role_policy(RoleName=role_name, PolicyName="StoreAccess")
    assert "s3:GetObject" in str(policy["PolicyDocument"])
