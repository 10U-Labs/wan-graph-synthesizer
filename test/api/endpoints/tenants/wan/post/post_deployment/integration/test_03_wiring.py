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
