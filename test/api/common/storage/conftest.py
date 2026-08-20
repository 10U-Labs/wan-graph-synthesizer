"""Shared fixtures for the common/storage stack tests.

These fixtures parse the stack's declared OpenTofu config (no AWS, no apply) so
that every tier -- unit, pre-deployment, post-deployment -- agrees on where the
stack lives and what the store bucket is named.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from repo_utils import REPO_ROOT
from test_module_utils import create_lambda_loader
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


@pytest.fixture(name="storage_iam")
def storage_iam_fixture() -> dict[str, object]:
    """Return the parsed ``iam.tf`` for the common/storage stack."""
    return load_tf(STORAGE_DIR / "iam.tf")


@pytest.fixture(name="prune_handler")
def prune_handler_fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the store's prune handler with the bucket name set.

    Loaded from a path rather than through ``test_handler_contracts.load_handler``, which
    looks under ``src/api/endpoints/``: this handler belongs to the store itself rather
    than to a REST resource, so it sits in the stack that declares the bucket.
    """
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    module: Any = create_lambda_loader(STORAGE_DIR / "lambdas")(
        "handler.py", "storage_prune_handler"
    )
    module.clear_clients()
    return module


@pytest.fixture(name="store_bucket_name")
def store_bucket_name_fixture(storage_main: dict[str, object]) -> str:
    """Return the declared name of the product's S3 store bucket."""
    bucket = find_resource(storage_main, "aws_s3_bucket", "store")
    if bucket is None:
        raise AssertionError("aws_s3_bucket.store is not declared in main.tf")
    return str(bucket["bucket"])
