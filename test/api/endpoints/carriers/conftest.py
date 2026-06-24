"""Shared fixtures for the carriers endpoint stack tests.

These parse the stack's declared OpenTofu config (no AWS, no apply) and expose
the deterministic Lambda and IAM role names every tier needs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import lambda_handler_names, load_tf

CARRIERS_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "carriers"


@pytest.fixture(name="carriers_dir")
def carriers_dir_fixture() -> Path:
    """Return the directory holding the carriers endpoint stack."""
    return CARRIERS_DIR


@pytest.fixture(name="carriers_main")
def carriers_main_fixture() -> dict[str, object]:
    """Return the parsed ``main.tf`` for the carriers stack."""
    return load_tf(CARRIERS_DIR / "main.tf")


@pytest.fixture(name="carriers_iam")
def carriers_iam_fixture() -> dict[str, object]:
    """Return the parsed ``iam.tf`` for the carriers stack."""
    return load_tf(CARRIERS_DIR / "iam.tf")


@pytest.fixture(name="carriers_locals")
def carriers_locals_fixture(carriers_main: dict[str, object]) -> dict[str, Any]:
    """Return the ``locals`` block declared in the carriers main.tf."""
    blocks = carriers_main.get("locals", [])
    return blocks[0] if isinstance(blocks, list) and blocks else {}


@pytest.fixture(name="function_name")
def function_name_fixture() -> str:
    """Return the deterministic carriers Lambda function name."""
    return lambda_handler_names()["carriers"]


@pytest.fixture(name="role_name")
def role_name_fixture(carriers_locals: dict[str, Any]) -> str:
    """Return the carriers Lambda execution role name."""
    return str(carriers_locals["role_name"])
