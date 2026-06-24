"""Layer 2 (configuration): the live store is private, versioned, expiring builds."""
from __future__ import annotations

from typing import Any

import pytest


def test_versioning_is_enabled(s3_client: Any, store_bucket_name: str) -> None:
    """The live store bucket has versioning enabled."""
    response = s3_client.get_bucket_versioning(Bucket=store_bucket_name)
    assert response["Status"] == "Enabled"


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
