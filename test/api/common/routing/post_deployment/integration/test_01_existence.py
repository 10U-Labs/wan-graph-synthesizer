from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from seed import DEFAULT_API


def test_rest_api_exists(apigateway_client: Any, api_id: str) -> None:
    api = apigateway_client.get_rest_api(restApiId=api_id)
    assert api["name"] == "wan-synthesizer"


def test_every_live_route_sits_under_the_served_prefix(
        apigateway_client: Any, api_id: str) -> None:
    prefix = urlsplit(DEFAULT_API).path
    resources = apigateway_client.get_resources(restApiId=api_id, limit=500)["items"]
    paths = [item["path"] for item in resources if item["path"] not in ("/", prefix)]
    assert [path for path in paths if not path.startswith(f"{prefix}/")] == []
