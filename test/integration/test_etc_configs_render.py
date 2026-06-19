"""Integration test that every shipped ``etc/`` WAN map renders end-to-end.

The synthetic e2e fixture exercises the design logic but deliberately avoids the
production ``etc/*.yml`` files, so a bad operator pin -- an off-continent or mistyped
forced PoP that resolves to no carrier vertex -- renders fine in CI while breaking the
live config. This renders each shipped config through the service and asserts the design
comes back connected, so that class of breakage fails CI instead of only the browser.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wan_designer.service import available_wan_maps, design_for_wan_map

ETC_DIR = Path("etc")
WAN_MAP_IDS = sorted(entry["id"] for entry in available_wan_maps(ETC_DIR))


@pytest.mark.parametrize("wan_map_id", WAN_MAP_IDS)
def test_shipped_etc_config_renders_a_connected_design(wan_map_id: str) -> None:
    """Each shipped ``etc/`` WAN map renders to a connected design over the service."""
    payload = design_for_wan_map(ETC_DIR, wan_map_id, {})
    assert payload["validation"]["connected"] is True


def test_military_installations_seats_the_forced_off_net_aggregations() -> None:
    """Charleston, SC and Montgomery, AL seat as aggregations once force-pinned."""
    payload = design_for_wan_map(ETC_DIR, "military_installations", {})
    aggregations = {
        vertex["name"] for vertex in payload["vertices"] if vertex["tier_role"] == "aggregation"
    }
    assert {"Charleston, SC", "Montgomery, AL"} <= aggregations
