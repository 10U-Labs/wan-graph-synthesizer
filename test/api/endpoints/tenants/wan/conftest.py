"""Shared fixtures for the tenants/wan endpoint stack tests.

These parse the stack's declared OpenTofu config (no AWS, no apply) and expose
the deterministic Lambda and IAM role names every tier needs. The synthesizer
runtime infra (ECR, ECS cluster, Fargate task, EventBridge recovery) is declared
in the same stack and parsed here too.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import find_resource, lambda_handler_names, load_tf

WAN_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "tenants" / "wan"


@pytest.fixture(name="wan_dir")
def wan_dir_fixture() -> Path:
    """Return the directory holding the tenants/wan endpoint stack."""
    return WAN_DIR


@pytest.fixture(name="wan_main")
def wan_main_fixture() -> dict[str, object]:
    """Return the parsed ``main.tf`` for the wan stack (synthesizer infra)."""
    return load_tf(WAN_DIR / "main.tf")


@pytest.fixture(name="wan_lambda")
def wan_lambda_fixture() -> dict[str, object]:
    """Return the parsed ``lambda.tf`` for the wan stack."""
    return load_tf(WAN_DIR / "lambda.tf")


@pytest.fixture(name="wan_iam")
def wan_iam_fixture() -> dict[str, object]:
    """Return the parsed ``iam_lambda.tf`` for the wan stack."""
    return load_tf(WAN_DIR / "iam_lambda.tf")


@pytest.fixture(name="wan_eventbridge")
def wan_eventbridge_fixture() -> dict[str, object]:
    """Return the parsed ``eventbridge.tf`` for the wan stack."""
    return load_tf(WAN_DIR / "eventbridge.tf")


@pytest.fixture(name="function_name")
def function_name_fixture() -> str:
    """Return the deterministic wan Lambda function name."""
    return lambda_handler_names()["wan"]


@pytest.fixture(name="role_name")
def role_name_fixture(wan_iam: dict[str, object]) -> str:
    """Return the wan Lambda execution role name declared in iam_lambda.tf."""
    role = find_resource(wan_iam, "aws_iam_role", "lambda")
    if role is None:
        raise AssertionError("aws_iam_role.lambda is not declared")
    return str(role["name"])
