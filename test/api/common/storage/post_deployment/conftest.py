from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(name="live_lifecycle_rules")
def live_lifecycle_rules_fixture(
        s3_client: Any, store_bucket_name: str) -> dict[str, Any]:
    response = s3_client.get_bucket_lifecycle_configuration(Bucket=store_bucket_name)
    rules: list[dict[str, Any]] = response["Rules"]
    return {rule["ID"]: rule for rule in rules}
