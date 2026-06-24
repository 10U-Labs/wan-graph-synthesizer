"""Shared fixtures for the csps endpoint stack tests.

These parse the stack's declared OpenTofu config (no AWS, no apply) and expose
the deterministic Lambda and IAM role names every tier needs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import lambda_handler_names, load_tf

CSPS_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "csps"


@pytest.fixture(name="csps_dir")
def csps_dir_fixture() -> Path:
    """Return the directory holding the csps endpoint stack."""
    return CSPS_DIR


@pytest.fixture(name="csps_main")
def csps_main_fixture() -> dict[str, object]:
    """Return the parsed ``main.tf`` for the csps stack."""
    return load_tf(CSPS_DIR / "main.tf")


@pytest.fixture(name="csps_iam")
def csps_iam_fixture() -> dict[str, object]:
    """Return the parsed ``iam.tf`` for the csps stack."""
    return load_tf(CSPS_DIR / "iam.tf")


@pytest.fixture(name="csps_locals")
def csps_locals_fixture(csps_main: dict[str, object]) -> dict[str, Any]:
    """Return the ``locals`` block declared in the csps main.tf."""
    blocks = csps_main.get("locals", [])
    return blocks[0] if isinstance(blocks, list) and blocks else {}


@pytest.fixture(name="function_name")
def function_name_fixture() -> str:
    """Return the deterministic csps Lambda function name."""
    return lambda_handler_names()["csps"]


@pytest.fixture(name="role_name")
def role_name_fixture(csps_locals: dict[str, Any]) -> str:
    """Return the csps Lambda execution role name."""
    return str(csps_locals["role_name"])
