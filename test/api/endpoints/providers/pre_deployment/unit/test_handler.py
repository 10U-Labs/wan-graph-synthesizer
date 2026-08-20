"""Unit tests for the providers endpoint Lambda handler.

The providers endpoint stores a single fixed regions object (no id, no listing), so
its tests are the single-resource contract bound to the endpoint's data.
"""

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
    """The single-resource contract, applied to the providers endpoint."""

    CFG = _CFG
