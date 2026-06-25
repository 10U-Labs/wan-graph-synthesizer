"""Derived fixtures for the data-centers post-deployment integration tier.

``lambda_config`` fetches the live Lambda's configuration once (the
``lambda_client`` and ``function_name`` fixtures come from parent conftests) so
the existence, configuration, and wiring layers share a single API call.
"""
from __future__ import annotations

from typing import Any, cast

import pytest


@pytest.fixture(name="lambda_config")
def lambda_config_fixture(lambda_client: Any, function_name: str) -> dict[str, Any]:
    """Return the live data-centers Lambda's configuration block."""
    response = lambda_client.get_function(FunctionName=function_name)
    return cast("dict[str, Any]", response["Configuration"])
