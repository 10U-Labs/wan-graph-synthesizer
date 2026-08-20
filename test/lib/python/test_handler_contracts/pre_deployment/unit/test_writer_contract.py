"""The shared write-side contract, exercised as the machinery it is.

Whatever an endpoint does with a write is the same for all of them, so it is written once
here: a collection is replaced rather than added to, rows that are not rows are refused, an
unknown collection is a 404, a write starts no build, and a delete removes the object. Two
endpoints inherit the lot and supply only the events they are addressed by.

Binding it here is what makes the contract itself run rather than only its consumers. The
delete and the refusals are the tests that would otherwise be reported against an endpoint
when what moved was this file.
"""

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
    """The write-side contract as an id-keyed endpoint is addressed, bound so that it runs."""

    CFG = _CFG
