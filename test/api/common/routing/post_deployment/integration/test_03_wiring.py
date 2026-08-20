"""Layer 3 (wiring): the live gateway's stage and resources are connected.

A stage with no deployment serves nothing, and an API with only its root resource
means the OpenAPI body never produced any. Both would pass existence yet leave
the gateway non-functional, so they are checked here.
"""
from __future__ import annotations

from typing import Any
from urllib.request import urlopen

from seed import DEFAULT_API


def test_prod_stage_points_to_a_deployment(apigateway_client: Any, api_id: str) -> None:
    """The prod stage is bound to a deployment."""
    stage = apigateway_client.get_stage(restApiId=api_id, stageName="prod")
    assert stage["deploymentId"]


def test_api_has_resources_beyond_root(apigateway_client: Any, api_id: str) -> None:
    """The OpenAPI body produced resources beyond the root path."""
    resources = apigateway_client.get_resources(restApiId=api_id, limit=500)["items"]
    assert len(resources) > 1


def test_a_request_through_cloudfront_reaches_the_gateway() -> None:
    """A GET to the base URL seed sends to answers 200.

    Every caller outside AWS crosses a CloudFront behaviour declared in another
    repository, which this one's deploys are not ordered against. Reading through it
    here is what puts that coupling in the run that changes the routes, rather than
    leaving it to ``seed.yml`` afterwards.
    """
    with urlopen(f"{DEFAULT_API}/tenants", timeout=30) as response:
        status = response.status
    assert status == 200
