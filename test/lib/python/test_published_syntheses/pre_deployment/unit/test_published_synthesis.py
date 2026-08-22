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
from test_published_syntheses import published_synthesis

_CONFIG: dict[str, Any] = {
    "backbone": {
        "coverage_target_miles": 200,
        "max_backup_path_multiple": 3.0,
        "node_count": {"max": 6},
        "number_of_diverse_paths": 2,
        "forced": {
            "nodes": ["Ashburn, VA"],
            "paths": [{"source": "Ashburn, VA", "target": "New York, NY"}],
        },
    },
}
_NODE = {"id": "ash", "name": "Ashburn, VA", "kind": "PoP", "coords": [39.0, -77.5]}
_SITE = {"id": "s1", "name": "Site", "kind": "Tenant site", "coords": [38.9, -77.0]}
_REGION = {"id": "r1", "name": "us-east-1", "kind": "provider region", "coords": [39.0, -78.0]}
_LINK = {"source_id": "ash", "target_id": "nyc", "distance_miles": 240.0, "path": ["ash", "nyc"]}
_SEGMENT = {
    "source_id": "ash", "target_id": "nyc", "distance_miles": 240.0,
    "link_kind": "carrier_physical",
}
_SUCCEEDED = {
    "status": "success",
    "coverage": {"target_miles": 200, "met": True},
    "backbone_lower_bound_miles": 1250.0,
}


def _answering(bodies: dict[str, Any], code: int = 200) -> Callable[..., FakeResponse]:
    def urlopen(request: urllib.request.Request, timeout: float = 0.0) -> FakeResponse:
        del timeout
        path = request.full_url.removeprefix(f"{DEFAULT_API}/")
        body = json.dumps(bodies[path]).encode()
        if code >= 400:
            raise HTTPError(request.full_url, code, "", Message(), BytesIO(body))
        return FakeResponse(code, body)
    return urlopen


def test_a_published_network_is_read_beside_the_demands_its_config_makes(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _answering({
        "tenants/daf/wan": _SUCCEEDED,
        "tenants/daf/backbone-nodes": [_NODE],
        "tenants/daf/backbone-links": [_LINK],
        "tenants/daf/tenant-nodes": [_SITE],
        "tenants/daf/provider-nodes": [_REGION],
        "tenants/daf/paths": [_SEGMENT],
    }))
    assert published_synthesis(DEFAULT_API, "daf", _CONFIG) == {
        "tenant": "daf",
        "target_miles": 200,
        "max_backup_path_multiple": 3.0,
        "number_of_diverse_paths": 2,
        "seat_cap": 6,
        "forced": ["Ashburn, VA"],
        "forced_paths": [{"source": "Ashburn, VA", "target": "New York, NY"}],
        "status": _SUCCEEDED,
        "lower_bound_miles": 1250.0,
        "backbone": [_NODE],
        "demand": [_SITE, _REGION],
        "links": [_LINK],
        "paths": [_SEGMENT],
    }


def test_a_tenant_whose_build_has_not_published_is_read_with_no_network(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _answering({
        "tenants/daf/wan": {"status": "synthesizing", "tenant": "daf"},
    }))
    synthesis = published_synthesis(DEFAULT_API, "daf", _CONFIG)
    assert [
        synthesis["backbone"], synthesis["demand"], synthesis["links"], synthesis["paths"]
    ] == [[], [], [], []]


def test_a_build_the_service_refuses_to_serve_is_read_as_what_it_says_went_wrong(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _answering({
        "tenants/daf/wan": {"status": "fail", "reason": "no valid WAN is possible"},
    }, code=422))
    assert published_synthesis(DEFAULT_API, "daf", _CONFIG)["status"] == {
        "status": "fail", "reason": "no valid WAN is possible",
    }
