"""Layer 2 (configuration): the live synthesizer matches its declaration."""
from __future__ import annotations

from typing import Any


def test_runtime_is_python313(synthesizer_config: dict[str, Any]) -> None:
    """The live synthesizer runs on Python 3.13."""
    assert synthesizer_config["Runtime"] == "python3.13"


def test_is_arm64(synthesizer_config: dict[str, Any]) -> None:
    """The live synthesizer runs on ARM64."""
    assert "arm64" in synthesizer_config["Architectures"]


def test_timeout_is_900_seconds(synthesizer_config: dict[str, Any]) -> None:
    """The live synthesizer's timeout is the Lambda maximum."""
    assert synthesizer_config["Timeout"] == 900


def test_memory_is_8192mb(synthesizer_config: dict[str, Any]) -> None:
    """The live synthesizer reserves 8192 MB, matching the prior Fargate task."""
    assert synthesizer_config["MemorySize"] == 8192


def test_entrypoint(synthesizer_config: dict[str, Any]) -> None:
    """The live synthesizer invokes ``synthesizer.handler.lambda_handler``."""
    assert synthesizer_config["Handler"] == "synthesizer.handler.lambda_handler"


def test_carries_the_store_bucket(synthesizer_config: dict[str, Any]) -> None:
    """The live synthesizer carries the STORE_BUCKET it reads inputs from and writes to."""
    assert "STORE_BUCKET" in synthesizer_config["Environment"]["Variables"]


def test_async_retries_are_disabled(synthesizer_invoke_config: dict[str, Any]) -> None:
    """The live synthesizer does not retry a failed async invocation."""
    assert synthesizer_invoke_config["MaximumRetryAttempts"] == 0


def test_failure_handler_runtime_is_python313(failure_handler_config: dict[str, Any]) -> None:
    """The live failure handler runs on Python 3.13."""
    assert failure_handler_config["Runtime"] == "python3.13"


def test_failure_handler_is_arm64(failure_handler_config: dict[str, Any]) -> None:
    """The live failure handler runs on ARM64."""
    assert "arm64" in failure_handler_config["Architectures"]


def test_failure_handler_entrypoint(failure_handler_config: dict[str, Any]) -> None:
    """The live failure handler invokes ``synthesizer.failure_handler.lambda_handler``."""
    assert failure_handler_config["Handler"] == "synthesizer.failure_handler.lambda_handler"


def test_failure_handler_carries_the_store_bucket(failure_handler_config: dict[str, Any]) -> None:
    """The live failure handler carries the STORE_BUCKET it writes the status marker to."""
    assert "STORE_BUCKET" in failure_handler_config["Environment"]["Variables"]
