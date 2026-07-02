"""Unit tests for the synthesizer stack's declared infrastructure.

Parse the synthesizer stack's ``main.tf`` with hcl2 and assert the synthesizer Lambda
(its runtime, size, handler, role and S3 access) and its log group are declared as
intended. No AWS calls, no apply. (The handler's runtime behaviour is covered by
``test_synthesizer.py``.)
"""
from __future__ import annotations

from typing import Any

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import find_resource, load_tf

SYNTH_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "tenants" / "wan" / "synthesizer"


@pytest.fixture(name="synth_main")
def synth_main_fixture() -> dict[str, object]:
    """Return the parsed ``main.tf`` for the synthesizer stack."""
    return load_tf(SYNTH_DIR / "main.tf")


def _resource(doc: dict[str, object], resource_type: str, name: str) -> dict[str, Any]:
    """Return the body of a named resource of the given type, or fail."""
    body = find_resource(doc, resource_type, name)
    if body is None:
        raise AssertionError(f"{resource_type}.{name} is not declared")
    return body


def test_synthesizer_runtime_is_python313(synth_main: dict[str, object]) -> None:
    """The synthesizer Lambda runs on Python 3.13."""
    synthesizer = _resource(synth_main, "aws_lambda_function", "synthesizer")
    assert synthesizer["runtime"] == "python3.13"


def test_synthesizer_is_arm64(synth_main: dict[str, object]) -> None:
    """The synthesizer Lambda runs on ARM64 (Graviton)."""
    synthesizer = _resource(synth_main, "aws_lambda_function", "synthesizer")
    assert synthesizer["architectures"] == ["arm64"]


def test_synthesizer_handler(synth_main: dict[str, object]) -> None:
    """The synthesizer invokes ``synthesizer.handler.lambda_handler``."""
    synthesizer = _resource(synth_main, "aws_lambda_function", "synthesizer")
    assert synthesizer["handler"] == "synthesizer.handler.lambda_handler"


def test_synthesizer_memory_matches_the_old_fargate_size(synth_main: dict[str, object]) -> None:
    """The synthesizer reserves 8192 MB so ``enumeration_limit`` matches the 8 GB task."""
    synthesizer = _resource(synth_main, "aws_lambda_function", "synthesizer")
    assert synthesizer["memory_size"] == 8192


def test_synthesizer_timeout_is_the_lambda_maximum(synth_main: dict[str, object]) -> None:
    """The synthesizer's timeout is 900s (the Lambda maximum) -- ample over a ~5s build."""
    synthesizer = _resource(synth_main, "aws_lambda_function", "synthesizer")
    assert synthesizer["timeout"] == 900


def test_synthesizer_carries_the_store_bucket(synth_main: dict[str, object]) -> None:
    """The synthesizer is given the STORE_BUCKET it reads inputs from and writes the WAN to."""
    synthesizer = _resource(synth_main, "aws_lambda_function", "synthesizer")
    assert "STORE_BUCKET" in synthesizer["environment"][0]["variables"]


def test_synthesizer_role_is_declared(synth_main: dict[str, object]) -> None:
    """The synthesizer's own execution role is declared."""
    assert find_resource(synth_main, "aws_iam_role", "synthesizer") is not None


def test_synthesizer_role_grants_store_access(synth_main: dict[str, object]) -> None:
    """The synthesizer role can read inputs and write the WAN to the store."""
    policy = _resource(synth_main, "aws_iam_role_policy", "synthesizer_s3")
    assert "s3:PutObject" in str(policy["policy"])


def test_synthesizer_log_group_retention(synth_main: dict[str, object]) -> None:
    """The synthesizer's log group retains events for fourteen days."""
    log_group = _resource(synth_main, "aws_cloudwatch_log_group", "synthesizer")
    assert log_group["retention_in_days"] == 14
