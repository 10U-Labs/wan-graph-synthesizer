"""Unit tests for the API paths a tenant's published network is read from.

The order matters as much as the set does. The build state gates whether the five
collections are worth asking for at all, so it is read first, and the reader takes it off
the front of this list rather than building a second copy of the same path.
"""

from __future__ import annotations

from test_published_syntheses import request_paths


def test_the_build_state_is_asked_for_before_the_collections_it_gates() -> None:
    """Every path is the tenant's, the state leads, and the five collections follow."""
    assert request_paths("daf") == [
        "tenants/daf/wan",
        "tenants/daf/backbone-nodes",
        "tenants/daf/backbone-links",
        "tenants/daf/tenant-nodes",
        "tenants/daf/provider-nodes",
        "tenants/daf/paths",
    ]
