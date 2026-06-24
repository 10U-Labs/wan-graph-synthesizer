"""Layer 3 (wiring): the live expiry rule is bound to the builds/ working area.

This connects two declared intents on the running bucket: the disposable
``builds/`` prefix and the lifecycle rule that expires it. If the rule applied
to the whole bucket, published graphs would be deleted too.
"""
from __future__ import annotations

from typing import Any


def test_expiry_rule_is_scoped_to_the_builds_prefix(
        s3_client: Any, store_bucket_name: str) -> None:
    """The lifecycle rule that expires objects is scoped to ``builds/``."""
    response = s3_client.get_bucket_lifecycle_configuration(Bucket=store_bucket_name)
    rule = response["Rules"][0]
    assert rule["Filter"]["Prefix"] == "builds/"
