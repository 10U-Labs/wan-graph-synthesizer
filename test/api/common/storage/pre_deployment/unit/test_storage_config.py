"""Unit tests for the common/storage stack's declared configuration.

Parse the stack's ``.tf`` with hcl2 and assert the S3 store is declared private,
unversioned, and set to expire both build artifacts and the delete markers a
delete leaves behind. No AWS calls, no apply.

Every lifecycle rule is reached by its ``id``, never by its position, so adding a
rule cannot silently move which rule a test is describing.
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


def _rule(storage_main: dict[str, object], rule_id: str) -> dict[str, Any]:
    """Return the lifecycle rule carrying the given ``id``, or fail."""
    lifecycle = _store(storage_main, "aws_s3_bucket_lifecycle_configuration")
    rules: list[dict[str, Any]] = lifecycle["rule"]
    for rule in rules:
        if rule["id"] == rule_id:
            return rule
    raise AssertionError(f"no lifecycle rule is declared with id {rule_id}")


def _filter_of(rule: dict[str, Any]) -> dict[str, Any]:
    """Return a rule's filter body, empty when the rule scopes itself to nothing."""
    blocks: list[dict[str, Any] | None] = rule.get("filter") or [{}]
    return blocks[0] or {}


def test_store_bucket_is_declared(storage_main: dict[str, object]) -> None:
    """The S3 store bucket resource is declared."""
    assert find_resource(storage_main, "aws_s3_bucket", "store") is not None


def test_store_bucket_has_the_expected_name(storage_main: dict[str, object]) -> None:
    """The store bucket carries the product's deterministic name."""
    bucket = _store(storage_main, "aws_s3_bucket")
    assert bucket["bucket"] == "wan-synthesizer-store-us-east-2"


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


def test_versioning_is_suspended(storage_main: dict[str, object]) -> None:
    """The store bucket keeps one copy of each key, not a copy per overwrite."""
    versioning = _store(storage_main, "aws_s3_bucket_versioning")
    assert versioning["versioning_configuration"][0]["status"] == "Suspended"


def test_lifecycle_rule_is_enabled(storage_main: dict[str, object]) -> None:
    """The build-artifact expiry rule is enabled."""
    assert _rule(storage_main, "expire-build-artifacts")["status"] == "Enabled"


def test_lifecycle_rule_targets_the_builds_prefix(
        storage_main: dict[str, object]) -> None:
    """The expiry rule is scoped to the disposable ``builds/`` working area."""
    rule = _rule(storage_main, "expire-build-artifacts")
    assert rule["filter"][0]["prefix"] == "builds/"


def test_lifecycle_rule_expires_after_fourteen_days(
        storage_main: dict[str, object]) -> None:
    """Build artifacts expire fourteen days after creation."""
    rule = _rule(storage_main, "expire-build-artifacts")
    assert rule["expiration"][0]["days"] == 14


def test_delete_markers_are_expired(storage_main: dict[str, object]) -> None:
    """A delete marker with nothing left under it is taken out of the bucket."""
    rule = _rule(storage_main, "expire-delete-markers")
    assert rule["expiration"][0]["expired_object_delete_marker"] is True


def test_delete_marker_rule_declares_no_days(
        storage_main: dict[str, object]) -> None:
    """S3 rejects an expiration that sets a delete-marker flag alongside days."""
    rule = _rule(storage_main, "expire-delete-markers")
    assert "days" not in rule["expiration"][0]


def test_delete_marker_rule_covers_every_prefix(
        storage_main: dict[str, object]) -> None:
    """The delete-marker rule is scoped to the whole store, not one prefix."""
    assert _filter_of(_rule(storage_main, "expire-delete-markers")) == {}
