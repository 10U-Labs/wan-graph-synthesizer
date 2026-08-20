"""Derived fixtures for the synthesizer post-deployment integration tier.

``synthesizer_config`` fetches the live synthesizer Lambda configuration once (the
``lambda_client`` and ``function_name`` fixtures come from parent conftests) so the
existence, configuration, and wiring layers share the call. The synthesizer's name is
derived from the wan dispatcher name, matching the deploy-time derived name.

Every fixture here reads the shape of what was deployed and none of them reads a synthesis.
Whether the configs in ``etc/`` synthesize into the networks they ask for is asked by
test/scripts/seed/post_deployment/e2e/test_delivered_syntheses.py, which carries its own
``delivered_syntheses`` fixture and sits with the configs it measures (GitHub issue #49).
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
    return "wan-synthesizer-synthesizer"


@pytest.fixture(name="synthesizer_config")
def synthesizer_config_fixture(
        lambda_client: Any, synthesizer_function_name: str) -> dict[str, Any]:
    """Return the live synthesizer Lambda's configuration block."""
    response = lambda_client.get_function(FunctionName=synthesizer_function_name)
    return cast("dict[str, Any]", response["Configuration"])


@pytest.fixture(name="synthesizer_invoke_config")
def synthesizer_invoke_config_fixture(
        lambda_client: Any, synthesizer_function_name: str) -> dict[str, Any]:
    """Return the live synthesizer's async (event) invocation config."""
    response = lambda_client.get_function_event_invoke_config(
        FunctionName=synthesizer_function_name)
    return cast("dict[str, Any]", response)


@pytest.fixture(name="failure_handler_function_name")
def failure_handler_function_name_fixture(function_name: str) -> str:
    """Return the deterministic failure-handler Lambda name."""
    return f"{function_name}-failure-handler"


@pytest.fixture(name="failure_handler_role_name")
def failure_handler_role_name_fixture() -> str:
    """Return the failure handler's dedicated execution role name."""
    return "wan-synthesizer-failure-handler"


@pytest.fixture(name="failure_handler_config")
def failure_handler_config_fixture(
        lambda_client: Any, failure_handler_function_name: str) -> dict[str, Any]:
    """Return the live failure-handler Lambda's configuration block."""
    response = lambda_client.get_function(FunctionName=failure_handler_function_name)
    return cast("dict[str, Any]", response["Configuration"])
