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
