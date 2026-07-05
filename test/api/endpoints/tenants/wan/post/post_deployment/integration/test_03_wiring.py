"""Layer 3 (wiring): the live synthesizer is connected to its dependencies.

These verify the connections that existence and configuration cannot: the synthesizer
runs as its own dedicated role, and that role grants the store access it needs to read
inputs and write the WAN.
"""
from __future__ import annotations

from typing import Any


def test_synthesizer_assumes_its_own_role(
        synthesizer_config: dict[str, Any], synthesizer_role_name: str) -> None:
    """The live synthesizer runs as its own dedicated execution role."""
    assert synthesizer_config["Role"].endswith(f"role/{synthesizer_role_name}")


def test_synthesizer_role_grants_store_access(
        iam_client: Any, synthesizer_role_name: str) -> None:
    """The synthesizer role policy grants ``s3:PutObject`` to write the WAN."""
    policy = iam_client.get_role_policy(
        RoleName=synthesizer_role_name, PolicyName="store-access")
    assert "s3:PutObject" in str(policy["PolicyDocument"])


def test_synthesizer_on_failure_targets_the_failure_handler(
        synthesizer_invoke_config: dict[str, Any], failure_handler_function_name: str) -> None:
    """A failed synthesizer invocation is routed to the failure handler."""
    destination = synthesizer_invoke_config["DestinationConfig"]["OnFailure"]["Destination"]
    assert destination.endswith(f"function:{failure_handler_function_name}")


def test_synthesizer_role_may_invoke_the_failure_handler(
        iam_client: Any, synthesizer_role_name: str) -> None:
    """The synthesizer role may invoke its on_failure destination."""
    policy = iam_client.get_role_policy(
        RoleName=synthesizer_role_name, PolicyName="on-failure-destination")
    assert "lambda:InvokeFunction" in str(policy["PolicyDocument"])


def test_failure_handler_role_grants_store_write(
        iam_client: Any, failure_handler_role_name: str) -> None:
    """The failure handler role policy grants ``s3:PutObject`` to record the status."""
    policy = iam_client.get_role_policy(
        RoleName=failure_handler_role_name, PolicyName="store-write")
    assert "s3:PutObject" in str(policy["PolicyDocument"])
