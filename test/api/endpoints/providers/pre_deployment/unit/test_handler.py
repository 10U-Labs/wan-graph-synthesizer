from __future__ import annotations

from typing import Any

from test_handler_contracts import RegionsContract

_CFG: dict[str, Any] = {
    "endpoint": "providers",
    "key": "providers/regions.json",
    "valid": [{"name": "r", "municipality": "Denver", "state": "CO",
               "country": "United States", "latitude": 1.0, "longitude": 2.0}],
}


class TestProvidersRegions(RegionsContract):
    CFG = _CFG
