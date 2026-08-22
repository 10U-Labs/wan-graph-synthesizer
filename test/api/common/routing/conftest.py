from __future__ import annotations

from pathlib import Path

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import load_tf

ROUTING_DIR = REPO_ROOT / "src" / "api" / "common" / "routing"


@pytest.fixture(name="routing_dir")
def routing_dir_fixture() -> Path:
    return ROUTING_DIR


@pytest.fixture(name="routing_main")
def routing_main_fixture() -> dict[str, object]:
    return load_tf(ROUTING_DIR / "main.tf")
