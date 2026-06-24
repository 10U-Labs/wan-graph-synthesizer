"""Shared fixtures for the providers endpoint stack tests.

These parse the stack's declared OpenTofu config (no AWS, no apply) and expose
the deterministic Lambda and IAM role names every tier needs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import lambda_handler_names, load_tf

providerS_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "providers"


@pytest.fixture(name="providers_dir")
def providers_dir_fixture() -> Path:
    """Return the directory holding the providers endpoint stack."""
    return providerS_DIR


@pytest.fixture(name="providers_main")
def providers_main_fixture() -> dict[str, object]:
    """Return the parsed ``main.tf`` for the providers stack."""
    return load_tf(providerS_DIR / "main.tf")


@pytest.fixture(name="providers_iam")
def providers_iam_fixture() -> dict[str, object]:
    """Return the parsed ``iam.tf`` for the providers stack."""
    return load_tf(providerS_DIR / "iam.tf")


@pytest.fixture(name="providers_locals")
def providers_locals_fixture(providers_main: dict[str, object]) -> dict[str, Any]:
    """Return the ``locals`` block declared in the providers main.tf."""
    blocks = providers_main.get("locals", [])
    return blocks[0] if isinstance(blocks, list) and blocks else {}


@pytest.fixture(name="function_name")
def function_name_fixture() -> str:
    """Return the deterministic providers Lambda function name."""
    return lambda_handler_names()["providers"]


@pytest.fixture(name="role_name")
def role_name_fixture(providers_locals: dict[str, Any]) -> str:
    """Return the providers Lambda execution role name."""
    return str(providers_locals["role_name"])
