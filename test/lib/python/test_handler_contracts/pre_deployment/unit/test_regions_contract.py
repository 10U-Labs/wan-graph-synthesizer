"""The single-resource contract, exercised as the machinery it is.

One endpoint stores a fixed object rather than a resource per id, so a request names the
collection in its path and nothing else. Its read side, its 404s and its delete are all
addressed differently from the id-keyed endpoints, which is why they are a contract of
their own rather than a case inside the other one.

It has exactly one consumer, so nothing else would ever run it: a change here that broke
it would be reported against the providers endpoint, in the providers workflow, on
whichever push next touched that endpoint.
"""

from __future__ import annotations

from typing import Any

from test_handler_contracts import RegionsContract

_CFG: dict[str, Any] = {
    "endpoint": "providers",
    "key": "providers/vertices.json",
    "valid": [{"name": "us-west-2", "municipality": "Portland", "state": "OR",
               "country": "United States", "latitude": 45.52, "longitude": -122.68}],
}


class TestTheSingleResourceContract(RegionsContract):
    """The single-resource contract, bound to its one endpoint so that it runs."""

    CFG = _CFG
