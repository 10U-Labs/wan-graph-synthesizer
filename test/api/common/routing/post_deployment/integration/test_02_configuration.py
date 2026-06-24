"""Layer 2 (configuration): the live gateway is regional with a prod stage."""
from __future__ import annotations

from typing import Any


def test_endpoint_is_regional(apigateway_client: Any, api_id: str) -> None:
    """The live REST API uses a regional endpoint."""
    api = apigateway_client.get_rest_api(restApiId=api_id)
    assert "REGIONAL" in api["endpointConfiguration"]["types"]


def test_prod_stage_exists(apigateway_client: Any, api_id: str) -> None:
    """The live gateway exposes the ``prod`` stage."""
    stage = apigateway_client.get_stage(restApiId=api_id, stageName="prod")
    assert stage["stageName"] == "prod"
