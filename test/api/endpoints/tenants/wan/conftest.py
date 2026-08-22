from __future__ import annotations

from pathlib import Path

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import find_resource, lambda_handler_names, load_tf

WAN_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "tenants" / "wan"


@pytest.fixture(name="wan_dir")
def wan_dir_fixture() -> Path:
    return WAN_DIR


@pytest.fixture(name="wan_lambda")
def wan_lambda_fixture() -> dict[str, object]:
    return load_tf(WAN_DIR / "lambda.tf")


@pytest.fixture(name="wan_iam")
def wan_iam_fixture() -> dict[str, object]:
    return load_tf(WAN_DIR / "iam_lambda.tf")


@pytest.fixture(name="function_name")
def function_name_fixture() -> str:
    return lambda_handler_names()["wan"]


@pytest.fixture(name="role_name")
def role_name_fixture(wan_iam: dict[str, object]) -> str:
    role = find_resource(wan_iam, "aws_iam_role", "lambda")
    if role is None:
        raise AssertionError("aws_iam_role.lambda is not declared")
    return str(role["name"])
