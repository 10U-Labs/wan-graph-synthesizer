from __future__ import annotations

from typing import Any

from test_handler_contracts import RegionsContract

_CFG: dict[str, Any] = {
    "endpoint": "providers",
    "key": "providers/regions.json",
    "valid": [{"name": "us-west-2", "municipality": "Portland", "state": "OR",
               "country": "United States", "latitude": 45.52, "longitude": -122.68}],
}


class TestTheSingleResourceContract(RegionsContract):
    CFG = _CFG
