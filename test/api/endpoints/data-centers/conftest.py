"""Shared fixtures for the data-centers endpoint stack tests.

These parse the stack's declared OpenTofu config (no AWS, no apply) and expose
the deterministic Lambda and IAM role names every tier needs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import lambda_handler_names, load_tf

DATA_CENTERS_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "data-centers"


@pytest.fixture(name="data_centers_dir")
def data_centers_dir_fixture() -> Path:
    """Return the directory holding the data-centers endpoint stack."""
    return DATA_CENTERS_DIR


@pytest.fixture(name="data_centers_main")
def data_centers_main_fixture() -> dict[str, object]:
    """Return the parsed ``main.tf`` for the data-centers stack."""
    return load_tf(DATA_CENTERS_DIR / "main.tf")


@pytest.fixture(name="data_centers_iam")
def data_centers_iam_fixture() -> dict[str, object]:
    """Return the parsed ``iam.tf`` for the data-centers stack."""
    return load_tf(DATA_CENTERS_DIR / "iam.tf")


@pytest.fixture(name="data_centers_locals")
def data_centers_locals_fixture(data_centers_main: dict[str, object]) -> dict[str, Any]:
    """Return the ``locals`` block declared in the data-centers main.tf."""
    blocks = data_centers_main.get("locals", [])
    return blocks[0] if isinstance(blocks, list) and blocks else {}


@pytest.fixture(name="function_name")
def function_name_fixture() -> str:
    """Return the deterministic data-centers Lambda function name."""
    return lambda_handler_names()["datacenters"]


@pytest.fixture(name="role_name")
def role_name_fixture(data_centers_locals: dict[str, Any]) -> str:
    """Return the data-centers Lambda execution role name."""
    return str(data_centers_locals["role_name"])
