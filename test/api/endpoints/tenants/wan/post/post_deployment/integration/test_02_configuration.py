from __future__ import annotations

from typing import Any

from test_terraform_config import store_bucket_name


def test_runtime_is_python313(synthesizer_config: dict[str, Any]) -> None:
    assert synthesizer_config["Runtime"] == "python3.13"


def test_is_arm64(synthesizer_config: dict[str, Any]) -> None:
    assert "arm64" in synthesizer_config["Architectures"]


def test_timeout_is_900_seconds(synthesizer_config: dict[str, Any]) -> None:
    assert synthesizer_config["Timeout"] == 900


def test_memory_is_8192mb(synthesizer_config: dict[str, Any]) -> None:
    assert synthesizer_config["MemorySize"] == 8192


def test_entrypoint(synthesizer_config: dict[str, Any]) -> None:
    assert synthesizer_config["Handler"] == "synthesizer.handler.lambda_handler"


def test_carries_the_store_bucket(synthesizer_config: dict[str, Any]) -> None:
    assert "STORE_BUCKET" in synthesizer_config["Environment"]["Variables"]


def test_async_retries_are_disabled(synthesizer_invoke_config: dict[str, Any]) -> None:
    assert synthesizer_invoke_config["MaximumRetryAttempts"] == 0


def test_failure_handler_runtime_is_python313(failure_handler_config: dict[str, Any]) -> None:
    assert failure_handler_config["Runtime"] == "python3.13"


def test_failure_handler_is_arm64(failure_handler_config: dict[str, Any]) -> None:
    assert "arm64" in failure_handler_config["Architectures"]


def test_failure_handler_entrypoint(failure_handler_config: dict[str, Any]) -> None:
    assert failure_handler_config["Handler"] == "synthesizer.failure_handler.lambda_handler"


def test_failure_handler_carries_the_store_bucket(failure_handler_config: dict[str, Any]) -> None:
    assert "STORE_BUCKET" in failure_handler_config["Environment"]["Variables"]


def test_synthesizer_store_bucket_is_the_one_the_storage_stack_declares(
        synthesizer_config: dict[str, Any]) -> None:
    variables = synthesizer_config["Environment"]["Variables"]
    assert variables["STORE_BUCKET"] == store_bucket_name()


def test_failure_handler_store_bucket_is_the_one_the_storage_stack_declares(
        failure_handler_config: dict[str, Any]) -> None:
    variables = failure_handler_config["Environment"]["Variables"]
    assert variables["STORE_BUCKET"] == store_bucket_name()
