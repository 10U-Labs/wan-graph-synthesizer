"""Unit tests for the common/storage stack's declared configuration.

Parse the stack's ``.tf`` with hcl2 and assert the S3 store is declared private,
versioned, and set to expire build artifacts. No AWS calls, no apply.
"""
from __future__ import annotations

from typing import Any

import pytest

from test_terraform_config import find_resource


def _store(storage_main: dict[str, object], resource_type: str) -> dict[str, Any]:
    """Return the body of a ``store`` resource of the given type, or fail."""
    body = find_resource(storage_main, resource_type, "store")
    if body is None:
        raise AssertionError(f"{resource_type}.store is not declared in main.tf")
    return body


def test_store_bucket_is_declared(storage_main: dict[str, object]) -> None:
    """The S3 store bucket resource is declared."""
    assert find_resource(storage_main, "aws_s3_bucket", "store") is not None


def test_store_bucket_has_the_expected_name(storage_main: dict[str, object]) -> None:
    """The store bucket carries the product's deterministic name."""
    bucket = _store(storage_main, "aws_s3_bucket")
    assert bucket["bucket"] == "wan-graph-synthesizer-store-us-east-2"


@pytest.mark.parametrize("setting", [
    "block_public_acls",
    "block_public_policy",
    "ignore_public_acls",
    "restrict_public_buckets",
])
def test_public_access_is_blocked(
        storage_main: dict[str, object], setting: str) -> None:
    """Every public-access-block setting is enabled."""
    block = _store(storage_main, "aws_s3_bucket_public_access_block")
    assert block[setting] is True


def test_versioning_is_enabled(storage_main: dict[str, object]) -> None:
    """The store bucket has versioning enabled."""
    versioning = _store(storage_main, "aws_s3_bucket_versioning")
    assert versioning["versioning_configuration"][0]["status"] == "Enabled"


def test_lifecycle_rule_is_enabled(storage_main: dict[str, object]) -> None:
    """The build-artifact expiry rule is enabled."""
    lifecycle = _store(storage_main, "aws_s3_bucket_lifecycle_configuration")
    assert lifecycle["rule"][0]["status"] == "Enabled"


def test_lifecycle_rule_targets_the_builds_prefix(
        storage_main: dict[str, object]) -> None:
    """The expiry rule is scoped to the disposable ``builds/`` working area."""
    lifecycle = _store(storage_main, "aws_s3_bucket_lifecycle_configuration")
    assert lifecycle["rule"][0]["filter"][0]["prefix"] == "builds/"


def test_lifecycle_rule_expires_after_fourteen_days(
        storage_main: dict[str, object]) -> None:
    """Build artifacts expire fourteen days after creation."""
    lifecycle = _store(storage_main, "aws_s3_bucket_lifecycle_configuration")
    assert lifecycle["rule"][0]["expiration"][0]["days"] == 14
