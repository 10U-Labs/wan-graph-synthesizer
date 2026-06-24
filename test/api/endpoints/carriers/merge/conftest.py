"""Shared fixtures for the carriers/merge endpoint stack tests.

These parse the stack's declared OpenTofu config (no AWS, no apply) and expose
the deterministic Lambda and IAM role names every tier needs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import lambda_handler_names, load_tf

MERGE_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "carriers" / "merge"


@pytest.fixture(name="merge_dir")
def merge_dir_fixture() -> Path:
    """Return the directory holding the carriers/merge endpoint stack."""
    return MERGE_DIR


@pytest.fixture(name="merge_main")
def merge_main_fixture() -> dict[str, object]:
    """Return the parsed ``main.tf`` for the carriers/merge stack."""
    return load_tf(MERGE_DIR / "main.tf")


@pytest.fixture(name="merge_iam")
def merge_iam_fixture() -> dict[str, object]:
    """Return the parsed ``iam.tf`` for the carriers/merge stack."""
    return load_tf(MERGE_DIR / "iam.tf")


@pytest.fixture(name="merge_locals")
def merge_locals_fixture(merge_main: dict[str, object]) -> dict[str, Any]:
    """Return the ``locals`` block declared in the carriers/merge main.tf."""
    blocks = merge_main.get("locals", [])
    return blocks[0] if isinstance(blocks, list) and blocks else {}


@pytest.fixture(name="function_name")
def function_name_fixture() -> str:
    """Return the deterministic carriers/merge Lambda function name."""
    return lambda_handler_names()["merge"]


@pytest.fixture(name="role_name")
def role_name_fixture(merge_locals: dict[str, Any]) -> str:
    """Return the carriers/merge Lambda execution role name."""
    return str(merge_locals["role_name"])
