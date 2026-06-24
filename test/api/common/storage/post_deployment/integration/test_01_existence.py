"""Layer 1 (existence): the storage stack's resources exist in AWS."""
from __future__ import annotations

from typing import Any


def test_store_bucket_exists(s3_client: Any, store_bucket_name: str) -> None:
    """The product's S3 store bucket exists."""
    response = s3_client.head_bucket(Bucket=store_bucket_name)
    assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
