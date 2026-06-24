"""Boto3 fixtures for the routing post-deployment integration tier.

These run against live AWS after the gateway is reconciled. ``api_id`` resolves
the product's REST API by name so the existence/config/wiring layers can inspect
it without hardcoding a generated id.
"""
from __future__ import annotations

from typing import Any

import pytest

from test_fixtures.aws import apigateway_client

__all__ = ["apigateway_client"]

API_NAME = "wan-graph-synthesizer"


@pytest.fixture(name="api_id")
def api_id_fixture(apigateway_client: Any) -> str:
    """Resolve the product's REST API id by its name."""
    items = apigateway_client.get_rest_apis(limit=500)["items"]
    for api in items:
        if api["name"] == API_NAME:
            return str(api["id"])
    raise AssertionError(f"REST API '{API_NAME}' not found in AWS")
