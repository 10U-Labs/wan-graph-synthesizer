"""Shared fixtures for the common/storage stack tests.

These fixtures parse the stack's declared OpenTofu config (no AWS, no apply) so
that every tier -- unit, pre-deployment, post-deployment -- agrees on where the
stack lives and what the store bucket is named.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import find_resource, load_tf

STORAGE_DIR = REPO_ROOT / "src" / "api" / "common" / "storage"


@pytest.fixture(name="storage_dir")
def storage_dir_fixture() -> Path:
    """Return the directory holding the common/storage OpenTofu stack."""
    return STORAGE_DIR


@pytest.fixture(name="storage_main")
def storage_main_fixture() -> dict[str, object]:
    """Return the parsed ``main.tf`` for the common/storage stack."""
    return load_tf(STORAGE_DIR / "main.tf")


@pytest.fixture(name="store_bucket_name")
def store_bucket_name_fixture(storage_main: dict[str, object]) -> str:
    """Return the declared name of the product's S3 store bucket."""
    bucket = find_resource(storage_main, "aws_s3_bucket", "store")
    if bucket is None:
        raise AssertionError("aws_s3_bucket.store is not declared in main.tf")
    return str(bucket["bucket"])
