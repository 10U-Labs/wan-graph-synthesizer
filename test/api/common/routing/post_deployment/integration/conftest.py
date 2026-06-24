"""Derived fixtures for the routing post-deployment integration tier.

``api_id`` resolves the product's REST API by name (the ``apigateway_client``
fixture comes from the parent post-deployment conftest) so the existence,
configuration, and wiring layers inspect it without hardcoding a generated id.
"""
from __future__ import annotations

from typing import Any

import pytest

API_NAME = "wan-graph-synthesizer"


@pytest.fixture(name="api_id")
def api_id_fixture(apigateway_client: Any) -> str:
    """Resolve the product's REST API id by its name."""
    items = apigateway_client.get_rest_apis(limit=500)["items"]
    for api in items:
        if api["name"] == API_NAME:
            return str(api["id"])
    raise AssertionError(f"REST API '{API_NAME}' not found in AWS")
