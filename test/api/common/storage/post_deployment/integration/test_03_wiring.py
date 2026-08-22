from __future__ import annotations

from typing import Any


def test_expiry_rule_is_scoped_to_the_builds_prefix(
        live_lifecycle_rules: dict[str, Any]) -> None:
    rule = live_lifecycle_rules["expire-build-artifacts"]
    assert rule["Filter"]["Prefix"] == "builds/"
