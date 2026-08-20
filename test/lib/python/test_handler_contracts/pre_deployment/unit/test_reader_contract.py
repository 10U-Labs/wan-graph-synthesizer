"""The shared read-side contract, exercised as the machinery it is.

Three endpoints inherit these five tests, so what they assert is decided here rather than in
any of them. Nothing binds the contract until an endpoint supplies its data, which is why
it is bound here too: a contract nobody applies is a contract nobody has run, and its
first run would otherwise be inside whichever endpoint's workflow next changed.

The carriers endpoint is the plainest instance of the read/write framework, so it is
the one the contract is held against here. That the endpoint's own workflow does the same
with its own data is not a duplicate: this run answers for the contract, and that one
answers for the endpoint.
"""

from __future__ import annotations

from typing import Any

from test_handler_contracts import ReaderContract

_CFG: dict[str, Any] = {
    "endpoint": "carriers",
    "list_keys": [
        "carriers/telia/pops.json",
        "carriers/arelion/pops.json",
        "carriers/merge/pops.json",
    ],
    "ids": ["arelion", "telia"],
    "stored_key": "carriers/telia/pops.json",
    "stored": [{"id": "denver-1"}],
    "serve_event": {
        "pathParameters": {"carrier": "telia"},
        "path": "/x/carriers/telia/pops",
    },
    "serve_expect": [{"id": "denver-1"}],
    "unknown_event": {
        "pathParameters": {"carrier": "telia"},
        "path": "/x/carriers/telia/regions",
    },
    "notbuilt_event": {
        "pathParameters": {"carrier": "arelion"},
        "path": "/x/carriers/arelion/pops",
    },
}


class TestTheReadContract(ReaderContract):
    """The read-side contract, bound to one endpoint so that it runs."""

    CFG = _CFG
