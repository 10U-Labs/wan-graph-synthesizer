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


def test_the_store_holds_the_product_it_is_supposed_to_hold(
        s3_client: Any, store_bucket_name: str) -> None:
    """Every prefix the product publishes under has at least one object in it.

    A bucket renamed without its objects copied is configured exactly as this tier's
    other tests expect and holds nothing, so this is the only assertion here that tells
    the store apart from an empty bucket wearing its name.
    """
    prefixes = ("carriers/", "providers/", "tenants/")
    empty = [
        prefix for prefix in prefixes
        if not s3_client.list_objects_v2(
            Bucket=store_bucket_name, Prefix=prefix, MaxKeys=1).get("Contents")
    ]
    assert empty == []


def test_build_artifacts_expire_after_fourteen_days(
        live_lifecycle_rules: dict[str, Any]) -> None:
    """The live lifecycle rule expires build artifacts after fourteen days."""
    rule = live_lifecycle_rules["expire-build-artifacts"]
    assert rule["Expiration"]["Days"] == 14


def test_delete_markers_are_expired_on_the_live_store(
        live_lifecycle_rules: dict[str, Any]) -> None:
    """The live store takes away a delete marker with nothing left under it."""
    rule = live_lifecycle_rules["expire-delete-markers"]
    assert rule["Expiration"]["ExpiredObjectDeleteMarker"] is True


def test_the_live_store_holds_nothing_the_product_no_longer_writes(
        s3_client: Any, store_bucket_name: str, prune_handler: Any) -> None:
    """Every object in the live store is one the product writes today.

    Renaming a collection writes the new key and leaves the old one behind, and a leftover
    is not inert: ``carriers/lumen/vertices.json`` was merged in as fiber and failed every
    tenant's build on 2026-08-20 (GitHub issue #102). ``scripts/seed.py`` asks the store to
    prune on every seed, so this is the assertion that says the prune ran and did its job --
    a rename that lands without one fails here rather than in some later reader.

    The prune's own idea of what is current is what the store is measured against, because
    a second list written here would be the same defect one file over.
    """
    stale = [
        item["Key"]
        for page in s3_client.get_paginator("list_objects_v2").paginate(
            Bucket=store_bucket_name)
        for item in page.get("Contents", [])
        if not prune_handler.is_current(item["Key"])
    ]
    assert stale == []
