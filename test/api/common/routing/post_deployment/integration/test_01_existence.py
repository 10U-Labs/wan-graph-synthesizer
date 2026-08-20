"""Layer 1 (existence): the routing gateway exists in AWS."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from seed import DEFAULT_API


def test_rest_api_exists(apigateway_client: Any, api_id: str) -> None:
    """The product's REST API exists under its declared name."""
    api = apigateway_client.get_rest_api(restApiId=api_id)
    assert api["name"] == "wan-synthesizer"


def test_every_live_route_sits_under_the_served_prefix(
        apigateway_client: Any, api_id: str) -> None:
    """Every resource the live gateway declares begins with the prefix seed sends to.

    The prefix is the one part of the rename a caller outside AWS can see, and it is
    written in the spec, in ``scripts/seed.py`` and in another repository's CloudFront
    behaviour. This is the assertion that the gateway agrees with the caller.
    """
    prefix = urlsplit(DEFAULT_API).path
    resources = apigateway_client.get_resources(restApiId=api_id, limit=500)["items"]
    paths = [item["path"] for item in resources if item["path"] != "/"]
    assert [path for path in paths if not path.startswith(f"{prefix}/")] == []
