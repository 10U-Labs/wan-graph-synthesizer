"""Layer 2 (configuration): the live store is private, unversioned, expiring builds.

The store keeps one copy of each key. Versioning is suspended, so an overwrite
replaces what was there instead of stacking another copy behind it, and the two
listing tests below read the live bucket to confirm nothing is stacked up.
"""
from __future__ import annotations

from typing import Any

import pytest


def _listings(s3_client: Any, bucket: str) -> list[dict[str, Any]]:
    """Every page ``list_object_versions`` returns for the bucket."""
    return list(s3_client.get_paginator("list_object_versions").paginate(Bucket=bucket))


def test_versioning_is_suspended(s3_client: Any, store_bucket_name: str) -> None:
    """The live store bucket has versioning suspended."""
    response = s3_client.get_bucket_versioning(Bucket=store_bucket_name)
    assert response["Status"] == "Suspended"


def test_no_superseded_copy_is_stored(s3_client: Any, store_bucket_name: str) -> None:
    """No key in the live store has an older copy of itself stored behind it."""
    superseded = {
        version["Key"]
        for page in _listings(s3_client, store_bucket_name)
        for version in page.get("Versions", [])
        if not version["IsLatest"]
    }
    assert superseded == set()


def test_no_delete_marker_is_left_behind(s3_client: Any, store_bucket_name: str) -> None:
    """No deleted key in the live store is still listed behind a delete marker."""
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
    """Every public-access-block setting is enforced on the live bucket."""
    response = s3_client.get_public_access_block(Bucket=store_bucket_name)
    assert response["PublicAccessBlockConfiguration"][setting] is True


def test_build_artifacts_expire_after_fourteen_days(
        s3_client: Any, store_bucket_name: str) -> None:
    """The live lifecycle rule expires build artifacts after fourteen days."""
    response = s3_client.get_bucket_lifecycle_configuration(Bucket=store_bucket_name)
    assert response["Rules"][0]["Expiration"]["Days"] == 14
