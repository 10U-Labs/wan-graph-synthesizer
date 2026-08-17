"""Unit tests for reading one tenant's published network from the API.

The service is replaced by a stand-in that answers each path from a canned document, so
what is held to account here is what the reader asks for and what it makes of the answers,
with no deployment and no network involved. The three cases are the three answers the WAN
endpoint gives: a build that has published, a build still running, and a build that failed,
which the endpoint reports by refusing the request with a 422 whose body says so.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from email.message import Message
from io import BytesIO
from typing import Any
from urllib.error import HTTPError

import pytest

from seed import DEFAULT_API
from test_http_doubles import FakeResponse
from test_published_designs import published_design

# One tenant's config as ``etc/`` declares it, cut down to the block the reader reads.
_CONFIG: dict[str, Any] = {
    "backbone": {
        "coverage_target_miles": 200,
        "max_backup_route_multiple": 3.0,
        "node_count": {"max": 6},
        "forced": {"nodes": ["Ashburn, VA"]},
    },
}
_NODE = {"id": "ash", "name": "Ashburn, VA", "kind": "PoP", "coords": [39.0, -77.5]}
_SITE = {"id": "s1", "name": "Site", "kind": "Tenant site", "coords": [38.9, -77.0]}
_REGION = {"id": "r1", "name": "us-east-1", "kind": "provider region", "coords": [39.0, -78.0]}
_LINK = {"source_id": "ash", "target_id": "nyc", "distance_miles": 240.0, "path": ["ash", "nyc"]}
_SPAN = {
    "source_id": "ash", "target_id": "nyc", "distance_miles": 240.0,
    "edge_kind": "carrier_physical",
}
_READY = {"status": "ready", "coverage": {"target_miles": 200, "met": True}}


def _answering(bodies: dict[str, Any], code: int = 200) -> Callable[..., FakeResponse]:
    """A ``urlopen`` stand-in answering each path out of *bodies* with status *code*.

    A code of 400 or more is raised rather than returned, which is what urllib does with
    the 422 the WAN endpoint answers with for a build that failed.
    """
    def urlopen(request: urllib.request.Request, timeout: float = 0.0) -> FakeResponse:
        """Answer one request from the canned bodies, by the path it names."""
        del timeout
        path = request.full_url.removeprefix(f"{DEFAULT_API}/")
        body = json.dumps(bodies[path]).encode()
        if code >= 400:
            raise HTTPError(request.full_url, code, "", Message(), BytesIO(body))
        return FakeResponse(code, body)
    return urlopen


def test_a_published_network_is_read_beside_the_demands_its_config_makes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``ready`` tenant carries its five collections and the five numbers git holds.

    The two demand collections arrive as one, since every site the coverage target applies
    to is measured the same way whether the tenant or a cloud provider owns it.
    """
    monkeypatch.setattr(urllib.request, "urlopen", _answering({
        "tenants/daf/wan": _READY,
        "tenants/daf/backbone-nodes": [_NODE],
        "tenants/daf/backbone-links": [_LINK],
        "tenants/daf/tenant-nodes": [_SITE],
        "tenants/daf/provider-nodes": [_REGION],
        "tenants/daf/edges": [_SPAN],
    }))
    assert published_design(DEFAULT_API, "daf", _CONFIG) == {
        "tenant": "daf",
        "target_miles": 200,
        "max_backup_route_multiple": 3.0,
        "seat_cap": 6,
        "forced": ["Ashburn, VA"],
        "status": _READY,
        "backbone": [_NODE],
        "demand": [_SITE, _REGION],
        "links": [_LINK],
        "edges": [_SPAN],
    }


def test_a_tenant_whose_build_has_not_published_is_read_with_no_network(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The collections are not asked for at all until a build has published one.

    They answer 404 until then, so asking would turn a tenant whose build is simply still
    running into an error that stops every test in the layer instead of one report.
    """
    monkeypatch.setattr(urllib.request, "urlopen", _answering({
        "tenants/daf/wan": {"status": "building", "tenant": "daf"},
    }))
    design = published_design(DEFAULT_API, "daf", _CONFIG)
    assert [
        design["backbone"], design["demand"], design["links"], design["edges"]
    ] == [[], [], [], []]


def test_a_build_the_service_refuses_to_serve_is_read_as_what_it_says_went_wrong(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed build is a state this layer reports, not an error it dies of.

    The endpoint answers 422 and urllib raises, but the body it raised with is the status
    document, and that document is what says which tenant failed and why.
    """
    monkeypatch.setattr(urllib.request, "urlopen", _answering({
        "tenants/daf/wan": {"status": "failed", "reason": "no valid WAN is possible"},
    }, code=422))
    assert published_design(DEFAULT_API, "daf", _CONFIG)["status"] == {
        "status": "failed", "reason": "no valid WAN is possible",
    }
