"""Layer 3 (wiring): the live expiry rule is bound to the builds/ working area.

This connects two declared intents on the running bucket: the disposable
``builds/`` prefix and the lifecycle rule that expires it. If the rule applied
to the whole bucket, published graphs would be deleted too.
"""
from __future__ import annotations

from typing import Any


def test_expiry_rule_is_scoped_to_the_builds_prefix(
        live_lifecycle_rules: dict[str, Any]) -> None:
    """The lifecycle rule that expires objects is scoped to ``builds/``."""
    rule = live_lifecycle_rules["expire-build-artifacts"]
    assert rule["Filter"]["Prefix"] == "builds/"
