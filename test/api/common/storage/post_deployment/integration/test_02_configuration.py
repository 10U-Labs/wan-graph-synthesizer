from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest

from repo_utils import REPO_ROOT
from test_terraform_config import lambda_handler_names, load_tf

SRC = REPO_ROOT / "src"
HANDLER_PREFIX = "wan-synthesizer-"

_REFERENCE = re.compile(r"\$\{([^{}]*)\}")


def _listings(s3_client: Any, bucket: str) -> list[dict[str, Any]]:
    return list(s3_client.get_paginator("list_object_versions").paginate(Bucket=bucket))


def test_versioning_is_suspended(s3_client: Any, store_bucket_name: str) -> None:
    response = s3_client.get_bucket_versioning(Bucket=store_bucket_name)
    assert response["Status"] == "Suspended"


def test_no_superseded_copy_is_stored(s3_client: Any, store_bucket_name: str) -> None:
    superseded = {
        version["Key"]
        for page in _listings(s3_client, store_bucket_name)
        for version in page.get("Versions", [])
        if not version["IsLatest"]
    }
    assert superseded == set()


def test_no_delete_marker_is_left_behind(s3_client: Any, store_bucket_name: str) -> None:
    hidden: set[str] = set()
    for page in _listings(s3_client, store_bucket_name):
        hidden.update(marker["Key"] for marker in page.get("DeleteMarkers", []))
    assert hidden == set()


@pytest.mark.parametrize("setting", [
    "BlockPublicAcls",
    "BlockPublicPolicy",
    "IgnorePublicAcls",
    "RestrictPublicBuckets",
])
def test_public_access_is_blocked(
        s3_client: Any, store_bucket_name: str, setting: str) -> None:
    response = s3_client.get_public_access_block(Bucket=store_bucket_name)
    assert response["PublicAccessBlockConfiguration"][setting] is True


def test_the_store_holds_the_product_it_is_supposed_to_hold(
        s3_client: Any, store_bucket_name: str) -> None:
    prefixes = ("carriers/", "providers/", "tenants/")
    empty = [
        prefix for prefix in prefixes
        if not s3_client.list_objects_v2(
            Bucket=store_bucket_name, Prefix=prefix, MaxKeys=1).get("Contents")
    ]
    assert empty == []


def test_build_artifacts_expire_after_fourteen_days(
        live_lifecycle_rules: dict[str, Any]) -> None:
    rule = live_lifecycle_rules["expire-build-artifacts"]
    assert rule["Expiration"]["Days"] == 14


def test_delete_markers_are_expired_on_the_live_store(
        live_lifecycle_rules: dict[str, Any]) -> None:
    rule = live_lifecycle_rules["expire-delete-markers"]
    assert rule["Expiration"]["ExpiredObjectDeleteMarker"] is True


def _lambda_bodies(document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for block in document.get("resource", []):
        yield from block.get("aws_lambda_function", {}).values()


def _resolved(expression: str, local_values: dict[str, str]) -> str:
    handlers = lambda_handler_names()

    def _substitute(match: re.Match[str]) -> str:
        reference = match.group(1).strip()
        if reference.startswith("local."):
            return local_values.get(reference.split(".", 1)[1], match.group(0))
        return handlers.get(reference.rsplit(".", 1)[-1], match.group(0))

    resolved = expression
    for _ in range(2):
        resolved = _REFERENCE.sub(_substitute, resolved)
    return resolved


def _declared_handler_names() -> set[str]:
    declared: set[str] = set()
    for path in sorted(SRC.rglob("*.tf")):
        document: dict[str, Any] = load_tf(path)
        local_values = {
            str(key): str(value)
            for block in document.get("locals", [])
            for key, value in block.items()
        }
        for body in _lambda_bodies(document):
            declared.add(_resolved(str(body["function_name"]), local_values))
    return declared


def test_no_lambda_is_left_over_from_a_deleted_stack(lambda_client: Any) -> None:
    live = {
        function["FunctionName"]
        for page in lambda_client.get_paginator("list_functions").paginate()
        for function in page["Functions"]
        if function["FunctionName"].startswith(HANDLER_PREFIX)
    }
    assert live - _declared_handler_names() == set()
