from __future__ import annotations

from typing import Any

import pytest

from test_terraform_config import find_resource


def _store(storage_main: dict[str, object], resource_type: str) -> dict[str, Any]:
    body = find_resource(storage_main, resource_type, "store")
    if body is None:
        raise AssertionError(f"{resource_type}.store is not declared in main.tf")
    return body


def _declared(document: dict[str, object], resource_type: str, name: str) -> dict[str, Any]:
    body = find_resource(document, resource_type, name)
    if body is None:
        raise AssertionError(f"{resource_type}.{name} is not declared")
    return body


def _rule(storage_main: dict[str, object], rule_id: str) -> dict[str, Any]:
    lifecycle = _store(storage_main, "aws_s3_bucket_lifecycle_configuration")
    rules: list[dict[str, Any]] = lifecycle["rule"]
    for rule in rules:
        if rule["id"] == rule_id:
            return rule
    raise AssertionError(f"no lifecycle rule is declared with id {rule_id}")


def _filter_of(rule: dict[str, Any]) -> dict[str, Any]:
    blocks: list[dict[str, Any] | None] = rule.get("filter") or [{}]
    return blocks[0] or {}


def test_store_bucket_is_declared(storage_main: dict[str, object]) -> None:
    assert find_resource(storage_main, "aws_s3_bucket", "store") is not None


def test_store_bucket_has_the_expected_name(storage_main: dict[str, object]) -> None:
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
    block = _store(storage_main, "aws_s3_bucket_public_access_block")
    assert block[setting] is True


def test_versioning_is_suspended(storage_main: dict[str, object]) -> None:
    versioning = _store(storage_main, "aws_s3_bucket_versioning")
    assert versioning["versioning_configuration"][0]["status"] == "Suspended"


def test_lifecycle_rule_is_enabled(storage_main: dict[str, object]) -> None:
    assert _rule(storage_main, "expire-build-artifacts")["status"] == "Enabled"


def test_lifecycle_rule_targets_the_builds_prefix(
        storage_main: dict[str, object]) -> None:
    rule = _rule(storage_main, "expire-build-artifacts")
    assert rule["filter"][0]["prefix"] == "builds/"


def test_lifecycle_rule_expires_after_fourteen_days(
        storage_main: dict[str, object]) -> None:
    rule = _rule(storage_main, "expire-build-artifacts")
    assert rule["expiration"][0]["days"] == 14


def test_delete_markers_are_expired(storage_main: dict[str, object]) -> None:
    rule = _rule(storage_main, "expire-delete-markers")
    assert rule["expiration"][0]["expired_object_delete_marker"] is True


def test_delete_marker_rule_declares_no_days(
        storage_main: dict[str, object]) -> None:
    rule = _rule(storage_main, "expire-delete-markers")
    assert "days" not in rule["expiration"][0]


def test_delete_marker_rule_covers_every_prefix(
        storage_main: dict[str, object]) -> None:
    assert _filter_of(_rule(storage_main, "expire-delete-markers")) == {}


def test_the_prune_handler_is_declared(storage_main: dict[str, object]) -> None:
    assert find_resource(storage_main, "aws_lambda_function", "prune") is not None


def test_the_prune_handler_is_handed_the_store_bucket(storage_main: dict[str, object]) -> None:
    handler = _declared(storage_main, "aws_lambda_function", "prune")
    assert handler["environment"][0]["variables"]["STORE_BUCKET"] == "${aws_s3_bucket.store.id}"


def _prune_policy(storage_iam: dict[str, object]) -> dict[str, Any]:
    return _declared(storage_iam, "aws_iam_role_policy", "prune_store_list_delete")


@pytest.mark.parametrize("action", ["s3:DeleteObject", "s3:DeleteObjectVersion"])
def test_the_prune_role_may_delete_from_the_store(
        storage_iam: dict[str, object], action: str) -> None:
    assert action in str(_prune_policy(storage_iam)["policy"])


@pytest.mark.parametrize("action", ["s3:PutObject", "s3:GetObject"])
def test_the_prune_role_may_do_nothing_else_to_the_store(
        storage_iam: dict[str, object], action: str) -> None:
    assert action not in str(_prune_policy(storage_iam)["policy"])
