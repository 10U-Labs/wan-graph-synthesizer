"""Layer 3 (wiring): the live gateway's stage and routes are connected.

A stage with no deployment serves nothing, and an API with only its root resource
means the OpenAPI body never produced routes. Both would pass existence yet leave
the gateway non-functional, so they are checked here.
"""
from __future__ import annotations

from typing import Any


def test_prod_stage_points_to_a_deployment(apigateway_client: Any, api_id: str) -> None:
    """The prod stage is bound to a deployment."""
    stage = apigateway_client.get_stage(restApiId=api_id, stageName="prod")
    assert stage["deploymentId"]


def test_api_has_routes_beyond_root(apigateway_client: Any, api_id: str) -> None:
    """The OpenAPI body produced resources beyond the root path."""
    resources = apigateway_client.get_resources(restApiId=api_id, limit=500)["items"]
    assert len(resources) > 1
