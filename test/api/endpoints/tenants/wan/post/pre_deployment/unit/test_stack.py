from __future__ import annotations

from typing import Any

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import find_resource, load_tf

SYNTH_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "tenants" / "wan" / "post"


@pytest.fixture(name="synth_main")
def synth_main_fixture() -> dict[str, object]:
    return load_tf(SYNTH_DIR / "main.tf")


def _resource(doc: dict[str, object], resource_type: str, name: str) -> dict[str, Any]:
    body = find_resource(doc, resource_type, name)
    if body is None:
        raise AssertionError(f"{resource_type}.{name} is not declared")
    return body


def test_synthesizer_runtime_is_python313(synth_main: dict[str, object]) -> None:
    synthesizer = _resource(synth_main, "aws_lambda_function", "synthesizer")
    assert synthesizer["runtime"] == "python3.13"


def test_synthesizer_is_arm64(synth_main: dict[str, object]) -> None:
    synthesizer = _resource(synth_main, "aws_lambda_function", "synthesizer")
    assert synthesizer["architectures"] == ["arm64"]


def test_synthesizer_handler(synth_main: dict[str, object]) -> None:
    synthesizer = _resource(synth_main, "aws_lambda_function", "synthesizer")
    assert synthesizer["handler"] == "synthesizer.handler.lambda_handler"


def test_synthesizer_memory_matches_the_old_fargate_size(synth_main: dict[str, object]) -> None:
    synthesizer = _resource(synth_main, "aws_lambda_function", "synthesizer")
    assert synthesizer["memory_size"] == 8192


def test_synthesizer_timeout_is_the_lambda_maximum(synth_main: dict[str, object]) -> None:
    synthesizer = _resource(synth_main, "aws_lambda_function", "synthesizer")
    assert synthesizer["timeout"] == 900


def test_synthesizer_carries_the_store_bucket(synth_main: dict[str, object]) -> None:
    synthesizer = _resource(synth_main, "aws_lambda_function", "synthesizer")
    assert "STORE_BUCKET" in synthesizer["environment"][0]["variables"]


def test_synthesizer_role_is_declared(synth_main: dict[str, object]) -> None:
    assert find_resource(synth_main, "aws_iam_role", "synthesizer") is not None


def test_synthesizer_role_grants_store_access(synth_main: dict[str, object]) -> None:
    policy = _resource(synth_main, "aws_iam_role_policy", "synthesizer_s3")
    assert "s3:PutObject" in str(policy["policy"])


def test_synthesizer_log_group_retention(synth_main: dict[str, object]) -> None:
    log_group = _resource(synth_main, "aws_cloudwatch_log_group", "synthesizer")
    assert log_group["retention_in_days"] == 14


def test_synthesizer_async_retries_are_disabled(synth_main: dict[str, object]) -> None:
    invoke_config = _resource(
        synth_main, "aws_lambda_function_event_invoke_config", "synthesizer")
    assert invoke_config["maximum_retry_attempts"] == 0


def test_synthesizer_on_failure_targets_the_failure_handler(synth_main: dict[str, object]) -> None:
    invoke_config = _resource(
        synth_main, "aws_lambda_function_event_invoke_config", "synthesizer")
    destination = invoke_config["destination_config"][0]["on_failure"][0]["destination"]
    assert "aws_lambda_function.failure_handler" in destination


def test_synthesizer_role_may_invoke_the_failure_handler(synth_main: dict[str, object]) -> None:
    policy = _resource(synth_main, "aws_iam_role_policy", "synthesizer_destination")
    assert "lambda:InvokeFunction" in str(policy["policy"])


def test_failure_handler_entrypoint(synth_main: dict[str, object]) -> None:
    failure_handler = _resource(synth_main, "aws_lambda_function", "failure_handler")
    assert failure_handler["handler"] == "synthesizer.failure_handler.lambda_handler"


def test_failure_handler_reuses_the_synthesizer_package(synth_main: dict[str, object]) -> None:
    failure_handler = _resource(synth_main, "aws_lambda_function", "failure_handler")
    assert "archive_file.synthesizer" in failure_handler["filename"]


def test_failure_handler_role_is_declared(synth_main: dict[str, object]) -> None:
    assert find_resource(synth_main, "aws_iam_role", "failure_handler") is not None


def test_failure_handler_role_grants_only_put_object(synth_main: dict[str, object]) -> None:
    policy = _resource(synth_main, "aws_iam_role_policy", "failure_handler_s3")
    assert "s3:PutObject" in str(policy["policy"])


def test_failure_handler_role_cannot_read(synth_main: dict[str, object]) -> None:
    policy = _resource(synth_main, "aws_iam_role_policy", "failure_handler_s3")
    assert "s3:GetObject" not in str(policy["policy"])


def test_failure_handler_log_group_retention(synth_main: dict[str, object]) -> None:
    log_group = _resource(synth_main, "aws_cloudwatch_log_group", "failure_handler")
    assert log_group["retention_in_days"] == 14


def test_solver_layer_is_declared(synth_main: dict[str, object]) -> None:
    assert find_resource(synth_main, "aws_lambda_layer_version", "solver") is not None


def test_solver_layer_runtime_is_python313(synth_main: dict[str, object]) -> None:
    layer = _resource(synth_main, "aws_lambda_layer_version", "solver")
    assert layer["compatible_runtimes"] == ["python3.13"]


def test_solver_layer_is_arm64(synth_main: dict[str, object]) -> None:
    layer = _resource(synth_main, "aws_lambda_layer_version", "solver")
    assert layer["compatible_architectures"] == ["arm64"]


def test_synthesizer_attaches_the_solver_layer(synth_main: dict[str, object]) -> None:
    synthesizer = _resource(synth_main, "aws_lambda_function", "synthesizer")
    assert "aws_lambda_layer_version.solver" in synthesizer["layers"][0]


def test_failure_handler_attaches_the_solver_layer(synth_main: dict[str, object]) -> None:
    failure_handler = _resource(synth_main, "aws_lambda_function", "failure_handler")
    assert "aws_lambda_layer_version.solver" in failure_handler["layers"][0]
