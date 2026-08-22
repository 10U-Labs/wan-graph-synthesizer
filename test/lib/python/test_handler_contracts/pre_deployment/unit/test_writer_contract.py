from __future__ import annotations

from typing import Any

from test_handler_contracts import WriterContract

_CFG: dict[str, Any] = {
    "endpoint": "carriers",
    "param": "carrier",
    "key": "carriers/telia/pops.json",
    "id": "telia",
    "valid": [{"municipality": "Reston", "state": "VA", "country": "United States",
               "latitude": 38.96, "longitude": -77.34}],
}


class TestTheWriteContract(WriterContract):
    CFG = _CFG
