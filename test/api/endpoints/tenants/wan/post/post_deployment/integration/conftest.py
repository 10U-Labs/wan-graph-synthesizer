from __future__ import annotations

from typing import Any, cast

import pytest


@pytest.fixture(name="synthesizer_function_name")
def synthesizer_function_name_fixture(function_name: str) -> str:
    return f"{function_name}-synthesizer"


@pytest.fixture(name="synthesizer_role_name")
def synthesizer_role_name_fixture() -> str:
    return "wan-synthesizer-synthesizer"


@pytest.fixture(name="synthesizer_config")
def synthesizer_config_fixture(
        lambda_client: Any, synthesizer_function_name: str) -> dict[str, Any]:
    response = lambda_client.get_function(FunctionName=synthesizer_function_name)
    return cast("dict[str, Any]", response["Configuration"])


@pytest.fixture(name="synthesizer_invoke_config")
def synthesizer_invoke_config_fixture(
        lambda_client: Any, synthesizer_function_name: str) -> dict[str, Any]:
    response = lambda_client.get_function_event_invoke_config(
        FunctionName=synthesizer_function_name)
    return cast("dict[str, Any]", response)


@pytest.fixture(name="failure_handler_function_name")
def failure_handler_function_name_fixture(function_name: str) -> str:
    return f"{function_name}-failure-handler"


@pytest.fixture(name="failure_handler_role_name")
def failure_handler_role_name_fixture() -> str:
    return "wan-synthesizer-failure-handler"


@pytest.fixture(name="failure_handler_config")
def failure_handler_config_fixture(
        lambda_client: Any, failure_handler_function_name: str) -> dict[str, Any]:
    response = lambda_client.get_function(FunctionName=failure_handler_function_name)
    return cast("dict[str, Any]", response["Configuration"])
