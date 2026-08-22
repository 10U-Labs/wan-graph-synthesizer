from __future__ import annotations

from typing import Any, cast

import pytest


@pytest.fixture(name="lambda_config")
def lambda_config_fixture(lambda_client: Any, function_name: str) -> dict[str, Any]:
    response = lambda_client.get_function(FunctionName=function_name)
    return cast("dict[str, Any]", response["Configuration"])
