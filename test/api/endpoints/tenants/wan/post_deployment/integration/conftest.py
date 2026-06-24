"""Derived fixtures for the wan post-deployment integration tier.

``lambda_config`` fetches the live Lambda's configuration once (the
``lambda_client`` and ``function_name`` fixtures come from parent conftests) so
the existence, configuration, and wiring layers share a single API call.
"""
from __future__ import annotations

from typing import Any, cast

import pytest


@pytest.fixture(name="lambda_config")
def lambda_config_fixture(lambda_client: Any, function_name: str) -> dict[str, Any]:
    """Return the live wan Lambda's configuration block."""
    response = lambda_client.get_function(FunctionName=function_name)
    return cast("dict[str, Any]", response["Configuration"])


@pytest.fixture(name="task_definition")
def task_definition_fixture(ecs_client: Any) -> dict[str, Any]:
    """Return the live synthesizer Fargate task definition block."""
    response = ecs_client.describe_task_definition(taskDefinition="wan-graph-synthesizer")
    return cast("dict[str, Any]", response["taskDefinition"])
