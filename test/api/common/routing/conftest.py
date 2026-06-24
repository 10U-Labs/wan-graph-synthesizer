"""Shared fixtures for the common/routing stack tests.

These parse the stack's declared OpenTofu config (no AWS, no apply) so every tier
agrees on where the routing gateway stack lives and how it is declared.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import load_tf

ROUTING_DIR = REPO_ROOT / "src" / "api" / "common" / "routing"


@pytest.fixture(name="routing_dir")
def routing_dir_fixture() -> Path:
    """Return the directory holding the common/routing OpenTofu stack."""
    return ROUTING_DIR


@pytest.fixture(name="routing_main")
def routing_main_fixture() -> dict[str, object]:
    """Return the parsed ``main.tf`` for the common/routing stack."""
    return load_tf(ROUTING_DIR / "main.tf")
