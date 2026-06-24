"""Shared fixtures for the tenants endpoint stack tests.

These parse the stack's declared OpenTofu config (no AWS, no apply) and expose
the deterministic Lambda and IAM role names every tier needs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import lambda_handler_names, load_tf

TENANTS_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "tenants"


@pytest.fixture(name="tenants_dir")
def tenants_dir_fixture() -> Path:
    """Return the directory holding the tenants endpoint stack."""
    return TENANTS_DIR


@pytest.fixture(name="tenants_main")
def tenants_main_fixture() -> dict[str, object]:
    """Return the parsed ``main.tf`` for the tenants stack."""
    return load_tf(TENANTS_DIR / "main.tf")


@pytest.fixture(name="tenants_iam")
def tenants_iam_fixture() -> dict[str, object]:
    """Return the parsed ``iam.tf`` for the tenants stack."""
    return load_tf(TENANTS_DIR / "iam.tf")


@pytest.fixture(name="tenants_locals")
def tenants_locals_fixture(tenants_main: dict[str, object]) -> dict[str, Any]:
    """Return the ``locals`` block declared in the tenants main.tf."""
    blocks = tenants_main.get("locals", [])
    return blocks[0] if isinstance(blocks, list) and blocks else {}


@pytest.fixture(name="function_name")
def function_name_fixture() -> str:
    """Return the deterministic tenants Lambda function name."""
    return lambda_handler_names()["tenants"]


@pytest.fixture(name="role_name")
def role_name_fixture(tenants_locals: dict[str, Any]) -> str:
    """Return the tenants Lambda execution role name."""
    return str(tenants_locals["role_name"])
