from __future__ import annotations

from typing import Any

import pytest

API_NAME = "wan-synthesizer"


@pytest.fixture(name="api_id")
def api_id_fixture(apigateway_client: Any) -> str:
    items = apigateway_client.get_rest_apis(limit=500)["items"]
    for api in items:
        if api["name"] == API_NAME:
            return str(api["id"])
    raise AssertionError(f"REST API '{API_NAME}' not found in AWS")
