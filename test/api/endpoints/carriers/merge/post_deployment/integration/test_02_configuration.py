from __future__ import annotations

from typing import Any

import pytest

from test_fixtures.aws import get_log_group_info
from test_terraform_config import store_bucket_name


def test_runtime_is_python313(lambda_config: dict[str, Any]) -> None:
    assert lambda_config["Runtime"] == "python3.13"


def test_is_arm64(lambda_config: dict[str, Any]) -> None:
    assert "arm64" in lambda_config["Architectures"]


def test_timeout_is_thirty_seconds(lambda_config: dict[str, Any]) -> None:
    assert lambda_config["Timeout"] == 30


def test_memory_is_256mb(lambda_config: dict[str, Any]) -> None:
    assert lambda_config["MemorySize"] == 256


def test_entrypoint(lambda_config: dict[str, Any]) -> None:
    assert lambda_config["Handler"] == "handler.lambda_handler"


@pytest.mark.parametrize("variable", ["STORE_BUCKET"])
def test_environment_variable_is_set(lambda_config: dict[str, Any], variable: str) -> None:
    assert variable in lambda_config["Environment"]["Variables"]


def test_log_group_retention_is_seven_days(logs_client: Any, function_name: str) -> None:
    info = get_log_group_info(logs_client, f"/aws/lambda/{function_name}")
    assert info["retention"] == 7


def test_store_bucket_is_the_one_the_storage_stack_declares(
        lambda_config: dict[str, Any]) -> None:
    variables = lambda_config["Environment"]["Variables"]
    assert variables["STORE_BUCKET"] == store_bucket_name()
