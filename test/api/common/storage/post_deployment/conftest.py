"""Fixtures shared by the storage post-deployment tiers.

The store's lifecycle rules are read once here and handed over keyed by the id
each rule carries. AWS does not promise the order it answers rules in, so a test
that means one rule has to name it rather than count to it.
"""
from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(name="live_lifecycle_rules")
def live_lifecycle_rules_fixture(
        s3_client: Any, store_bucket_name: str) -> dict[str, Any]:
    """Return the store's live lifecycle rules, keyed by the id each carries."""
    response = s3_client.get_bucket_lifecycle_configuration(Bucket=store_bucket_name)
    rules: list[dict[str, Any]] = response["Rules"]
    return {rule["ID"]: rule for rule in rules}
