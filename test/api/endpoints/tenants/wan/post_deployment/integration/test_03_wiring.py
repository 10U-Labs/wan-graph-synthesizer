from __future__ import annotations

from typing import Any


def test_lambda_assumes_the_declared_role(
        lambda_config: dict[str, Any], role_name: str) -> None:
    assert lambda_config["Role"].endswith(f"role/{role_name}")


def test_api_gateway_may_invoke_the_lambda(lambda_client: Any, function_name: str) -> None:
    policy = lambda_client.get_policy(FunctionName=function_name)["Policy"]
    assert "apigateway.amazonaws.com" in policy


def test_dispatch_role_grants_invoke(iam_client: Any, role_name: str) -> None:
    policy = iam_client.get_role_policy(RoleName=role_name, PolicyName="Dispatch")
    assert "lambda:InvokeFunction" in str(policy["PolicyDocument"])


def test_dispatch_role_targets_the_synthesizer(iam_client: Any, role_name: str) -> None:
    policy = iam_client.get_role_policy(RoleName=role_name, PolicyName="Dispatch")
    assert "-synthesizer" in str(policy["PolicyDocument"])


def test_dispatch_role_grants_listing_the_bucket(iam_client: Any, role_name: str) -> None:
    policy = iam_client.get_role_policy(RoleName=role_name, PolicyName="Dispatch")
    assert "s3:ListBucket" in str(policy["PolicyDocument"])
