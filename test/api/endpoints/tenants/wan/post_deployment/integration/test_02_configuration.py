"""Layer 2 (configuration): the live wan resources match their declaration."""
from __future__ import annotations

from typing import Any

import pytest


def test_runtime_is_python313(lambda_config: dict[str, Any]) -> None:
    """The live dispatcher runs on Python 3.13."""
    assert lambda_config["Runtime"] == "python3.13"


def test_is_arm64(lambda_config: dict[str, Any]) -> None:
    """The live dispatcher runs on ARM64."""
    assert "arm64" in lambda_config["Architectures"]


def test_timeout_is_ten_seconds(lambda_config: dict[str, Any]) -> None:
    """The live dispatcher's timeout matches the declaration."""
    assert lambda_config["Timeout"] == 10


def test_memory_is_128mb(lambda_config: dict[str, Any]) -> None:
    """The live dispatcher's memory matches the declaration."""
    assert lambda_config["MemorySize"] == 128


def test_entrypoint(lambda_config: dict[str, Any]) -> None:
    """The live dispatcher invokes ``handler.lambda_handler``."""
    assert lambda_config["Handler"] == "handler.lambda_handler"


@pytest.mark.parametrize("variable", ["STORE_BUCKET", "WORKER_FUNCTION_NAME"])
def test_environment_variable_is_set(lambda_config: dict[str, Any], variable: str) -> None:
    """The live dispatcher carries each environment variable it reads."""
    assert variable in lambda_config["Environment"]["Variables"]


def test_worker_runtime_is_python313(worker_config: dict[str, Any]) -> None:
    """The live worker runs on Python 3.13."""
    assert worker_config["Runtime"] == "python3.13"


def test_worker_is_arm64(worker_config: dict[str, Any]) -> None:
    """The live worker runs on ARM64."""
    assert "arm64" in worker_config["Architectures"]


def test_worker_timeout_is_900_seconds(worker_config: dict[str, Any]) -> None:
    """The live worker's timeout is the Lambda maximum."""
    assert worker_config["Timeout"] == 900


def test_worker_memory_is_8192mb(worker_config: dict[str, Any]) -> None:
    """The live worker reserves 8192 MB, matching the prior Fargate task."""
    assert worker_config["MemorySize"] == 8192


def test_worker_entrypoint(worker_config: dict[str, Any]) -> None:
    """The live worker invokes ``synthesizer.handler.lambda_handler``."""
    assert worker_config["Handler"] == "synthesizer.handler.lambda_handler"


def test_worker_carries_the_store_bucket(worker_config: dict[str, Any]) -> None:
    """The live worker carries the STORE_BUCKET it reads inputs from and writes to."""
    assert "STORE_BUCKET" in worker_config["Environment"]["Variables"]
