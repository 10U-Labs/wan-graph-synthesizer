"""Derived fixtures for the wan post-deployment integration tier.

``lambda_config`` and ``worker_config`` fetch the live dispatcher and worker Lambda
configurations once (the ``lambda_client`` and ``function_name`` fixtures come from
parent conftests) so the existence, configuration, and wiring layers share the calls.
"""
from __future__ import annotations

from typing import Any, cast

import pytest


@pytest.fixture(name="worker_function_name")
def worker_function_name_fixture(function_name: str) -> str:
    """Return the deterministic synthesizer worker Lambda name."""
    return f"{function_name}-worker"


@pytest.fixture(name="lambda_config")
def lambda_config_fixture(lambda_client: Any, function_name: str) -> dict[str, Any]:
    """Return the live wan dispatching Lambda's configuration block."""
    response = lambda_client.get_function(FunctionName=function_name)
    return cast("dict[str, Any]", response["Configuration"])


@pytest.fixture(name="worker_config")
def worker_config_fixture(lambda_client: Any, worker_function_name: str) -> dict[str, Any]:
    """Return the live synthesizer worker Lambda's configuration block."""
    response = lambda_client.get_function(FunctionName=worker_function_name)
    return cast("dict[str, Any]", response["Configuration"])
