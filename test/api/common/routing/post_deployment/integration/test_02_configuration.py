from __future__ import annotations

from typing import Any


def test_endpoint_is_regional(apigateway_client: Any, api_id: str) -> None:
    api = apigateway_client.get_rest_api(restApiId=api_id)
    assert "REGIONAL" in api["endpointConfiguration"]["types"]


def test_prod_stage_exists(apigateway_client: Any, api_id: str) -> None:
    stage = apigateway_client.get_stage(restApiId=api_id, stageName="prod")
    assert stage["stageName"] == "prod"
