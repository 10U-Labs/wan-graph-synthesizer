"""Layer 3 (wiring): the live wan dispatcher is connected to its dependencies.

These verify the connections that existence and configuration cannot: the dispatcher
assumes the declared role, API Gateway is allowed to invoke it, and the dispatch role
may invoke the synthesizer by its derived name (the synthesizer itself lives in its own
stack, verified by that stack's post-deployment suite).
"""
from __future__ import annotations

from typing import Any


def test_lambda_assumes_the_declared_role(
        lambda_config: dict[str, Any], role_name: str) -> None:
    """The live dispatcher runs as the declared execution role."""
    assert lambda_config["Role"].endswith(f"role/{role_name}")


def test_api_gateway_may_invoke_the_lambda(lambda_client: Any, function_name: str) -> None:
    """API Gateway holds permission to invoke the live dispatcher."""
    policy = lambda_client.get_policy(FunctionName=function_name)["Policy"]
    assert "apigateway.amazonaws.com" in policy


def test_dispatch_role_grants_invoke(iam_client: Any, role_name: str) -> None:
    """The dispatch role policy grants the Lambda ``lambda:InvokeFunction``."""
    policy = iam_client.get_role_policy(RoleName=role_name, PolicyName="Dispatch")
    assert "lambda:InvokeFunction" in str(policy["PolicyDocument"])


def test_dispatch_role_targets_the_synthesizer(iam_client: Any, role_name: str) -> None:
    """The dispatch invoke permission targets the synthesizer's derived function name."""
    policy = iam_client.get_role_policy(RoleName=role_name, PolicyName="Dispatch")
    assert "-synthesizer" in str(policy["PolicyDocument"])
