from __future__ import annotations

from typing import Any
from urllib.request import urlopen

from seed import DEFAULT_API


def test_prod_stage_points_to_a_deployment(apigateway_client: Any, api_id: str) -> None:
    stage = apigateway_client.get_stage(restApiId=api_id, stageName="prod")
    assert stage["deploymentId"]


def test_api_has_resources_beyond_root(apigateway_client: Any, api_id: str) -> None:
    resources = apigateway_client.get_resources(restApiId=api_id, limit=500)["items"]
    assert len(resources) > 1


def test_a_request_through_cloudfront_reaches_the_gateway() -> None:
    with urlopen(f"{DEFAULT_API}/tenants", timeout=30) as response:
        status = response.status
    assert status == 200
