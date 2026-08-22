from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import lambda_handler_names, load_tf

PROVIDERS_DIR = REPO_ROOT / "src" / "api" / "endpoints" / "providers"


@pytest.fixture(name="providers_dir")
def providers_dir_fixture() -> Path:
    return PROVIDERS_DIR


@pytest.fixture(name="providers_main")
def providers_main_fixture() -> dict[str, object]:
    return load_tf(PROVIDERS_DIR / "main.tf")


@pytest.fixture(name="providers_iam")
def providers_iam_fixture() -> dict[str, object]:
    return load_tf(PROVIDERS_DIR / "iam.tf")


@pytest.fixture(name="providers_locals")
def providers_locals_fixture(providers_main: dict[str, object]) -> dict[str, Any]:
    blocks = providers_main.get("locals", [])
    return blocks[0] if isinstance(blocks, list) and blocks else {}


@pytest.fixture(name="function_name")
def function_name_fixture() -> str:
    return lambda_handler_names()["providers"]


@pytest.fixture(name="role_name")
def role_name_fixture(providers_locals: dict[str, Any]) -> str:
    return str(providers_locals["role_name"])
