"""Derived fixtures for the synthesizer post-deployment integration tier.

``synthesizer_config`` fetches the live synthesizer Lambda configuration once (the
``lambda_client`` and ``function_name`` fixtures come from parent conftests) so the
existence, configuration, and wiring layers share the call. The synthesizer's name is
derived from the wan dispatcher name, matching the deploy-time derived name.
"""
from __future__ import annotations

from typing import Any, cast

import pytest


@pytest.fixture(name="synthesizer_function_name")
def synthesizer_function_name_fixture(function_name: str) -> str:
    """Return the deterministic synthesizer Lambda name."""
    return f"{function_name}-synthesizer"


@pytest.fixture(name="synthesizer_role_name")
def synthesizer_role_name_fixture() -> str:
    """Return the synthesizer Lambda's dedicated execution role name."""
    return "wan-graph-synthesizer-synthesizer"


@pytest.fixture(name="synthesizer_config")
def synthesizer_config_fixture(
        lambda_client: Any, synthesizer_function_name: str) -> dict[str, Any]:
    """Return the live synthesizer Lambda's configuration block."""
    response = lambda_client.get_function(FunctionName=synthesizer_function_name)
    return cast("dict[str, Any]", response["Configuration"])
