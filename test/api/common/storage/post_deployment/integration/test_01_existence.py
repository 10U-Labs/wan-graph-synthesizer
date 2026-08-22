from __future__ import annotations

from typing import Any


def test_store_bucket_exists(s3_client: Any, store_bucket_name: str) -> None:
    response = s3_client.head_bucket(Bucket=store_bucket_name)
    assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
