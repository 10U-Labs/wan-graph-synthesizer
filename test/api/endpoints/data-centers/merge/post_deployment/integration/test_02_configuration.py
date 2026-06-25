"""Layer 2 (configuration): the live data-centers/merge Lambda matches its declaration."""
from __future__ import annotations

from typing import Any

import pytest

from test_fixtures.aws import get_log_group_info


def test_runtime_is_python313(lambda_config: dict[str, Any]) -> None:
    """The live Lambda runs on Python 3.13."""
    assert lambda_config["Runtime"] == "python3.13"


def test_is_arm64(lambda_config: dict[str, Any]) -> None:
    """The live Lambda runs on ARM64."""
    assert "arm64" in lambda_config["Architectures"]


def test_timeout_is_thirty_seconds(lambda_config: dict[str, Any]) -> None:
    """The live Lambda's timeout matches the declaration."""
    assert lambda_config["Timeout"] == 30


def test_memory_is_256mb(lambda_config: dict[str, Any]) -> None:
    """The live Lambda's memory matches the declaration."""
    assert lambda_config["MemorySize"] == 256


def test_entrypoint(lambda_config: dict[str, Any]) -> None:
    """The live Lambda invokes ``handler.lambda_handler``."""
    assert lambda_config["Handler"] == "handler.lambda_handler"


@pytest.mark.parametrize("variable", ["STORE_BUCKET"])
def test_environment_variable_is_set(lambda_config: dict[str, Any], variable: str) -> None:
    """The live Lambda carries each environment variable it reads."""
    assert variable in lambda_config["Environment"]["Variables"]


def test_log_group_retention_is_seven_days(logs_client: Any, function_name: str) -> None:
    """The live log group retains events for seven days."""
    info = get_log_group_info(logs_client, f"/aws/lambda/{function_name}")
    assert info["retention"] == 7
