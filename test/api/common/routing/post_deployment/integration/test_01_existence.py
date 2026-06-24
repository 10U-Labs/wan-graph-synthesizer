"""Layer 1 (existence): the routing gateway exists in AWS."""
from __future__ import annotations

from typing import Any


def test_rest_api_exists(apigateway_client: Any, api_id: str) -> None:
    """The product's REST API exists under its declared name."""
    api = apigateway_client.get_rest_api(restApiId=api_id)
    assert api["name"] == "wan-graph-synthesizer"
