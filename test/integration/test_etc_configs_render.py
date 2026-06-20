"""Integration test that every shipped ``etc/`` WAN map renders end-to-end.

The synthetic e2e fixture exercises the design logic but deliberately avoids the
production ``etc/*.yml`` files, so a bad operator pin -- an off-continent or mistyped
forced PoP that resolves to no carrier vertex -- renders fine in CI while breaking the
live config. This renders each shipped config through the service and asserts the design
comes back connected, so that class of breakage fails CI instead of only the browser.
"""

from __future__ import annotations

import math
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


def _miles(point: tuple[float, float], other: tuple[float, float]) -> float:
    """Great-circle distance in miles between two (latitude, longitude) points."""
    lat1, lat2 = math.radians(point[0]), math.radians(other[0])
    delta_lat = math.radians(other[0] - point[0])
    delta_lon = math.radians(other[1] - point[1])
    inner = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * 3958.8 * math.asin(math.sqrt(inner))


def test_military_installations_places_a_hub_inside_a_spread_out_cluster() -> None:
    """A spread-out base group gets an aggregation near its center, not only distant ones.

    The Missouri/Kansas bases (Fort Leavenworth, Whiteman, Fort Riley, Fort Leonard
    Wood, McConnell) sit ~85-105 mi apart -- a spread-out group the old single-radius
    clustering dropped, leaving every base to reach a far-off facility. With the group
    now recognized and given a local head, an aggregation lands near the group's center
    rather than only at distant metros -- and with no forced pins in the config.
    """
    payload = design_for_wan_map(ETC_DIR, "military_installations", {})
    group_center = (38.5, -94.9)  # approximate center of the Missouri/Kansas base group
    hub_distances = [
        _miles(group_center, (float(vertex["coords"][0]), float(vertex["coords"][1])))
        for vertex in payload["vertices"]
        if vertex["tier_role"] == "aggregation"
    ]
    assert min(hub_distances) < 100.0
