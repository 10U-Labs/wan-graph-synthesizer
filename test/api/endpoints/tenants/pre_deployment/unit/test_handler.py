"""Unit tests for the tenants endpoint Lambda handler.

The read-side listing/serving comes from the shared contract. The tenant-specific
input documents, label listing, WAN re-creation and delete behaviour are here.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from test_handler_contracts import ReaderContract, load_handler, write_clients
from test_s3_store_mock import fake_s3

_READER: dict[str, Any] = {
    "endpoint": "tenants",
    "list_keys": ["tenants/f-35/label.json", "tenants/minuteman/label.json"],
    "ids": [{"id": "f-35", "label": "f-35"}, {"id": "minuteman", "label": "minuteman"}],
    "stored_key": "tenants/f-35/wan.json",
    "stored": {
        "sites": [],
        "paths": [],
        "backbone-nodes": [{"id": "P"}],
        "tenant-nodes": [],
        "provider-nodes": [],
    },
    "serve_event": {
        "pathParameters": {"tenant": "f-35"},
        "path": "/x/tenants/f-35/backbone-nodes",
    },
    "serve_expect": [{"id": "P"}],
    "unknown_event": {
        "pathParameters": {"tenant": "f-35"},
        "path": "/x/tenants/f-35/bogus",
    },
    "notbuilt_event": {
        "pathParameters": {"tenant": "minuteman"},
        "path": "/x/tenants/minuteman/paths",
    },
}


class TestTenantsReader(ReaderContract):
    """The shared read-side contract, applied to the tenants endpoint."""

    CFG = _READER


def _tenant(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the tenants handler."""
    return load_handler("tenants", monkeypatch)


def _tenant_put(collection: str, body: Any) -> dict[str, Any]:
    """A tenant input-document PUT event."""
    return {
        "httpMethod": "PUT",
        "pathParameters": {"tenant": "f-35"},
        "path": f"/x/tenants/f-35/{collection}",
        "body": json.dumps(body),
    }


def test_tenants_list_surfaces_each_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """The tenants collection returns each tenant's display label document."""
    module = _tenant(monkeypatch)
    objects = {
        "tenants/f-35/label.json": json.dumps({"label": "F-35"}).encode(),
        "tenants/minuteman/label.json": json.dumps({"label": "Minuteman"}).encode(),
    }
    with patch("boto3.client", return_value=fake_s3(objects)):
        response = module.lambda_handler({}, None)
    assert json.loads(response["body"]) == [
        {"id": "f-35", "label": "F-35"},
        {"id": "minuteman", "label": "Minuteman"},
    ]


def test_tenants_list_falls_back_to_id_without_a_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tenant whose label document is empty is listed with its id as the label."""
    module = _tenant(monkeypatch)
    with patch("boto3.client", return_value=fake_s3({"tenants/minuteman/label.json": b"{}"})):
        response = module.lambda_handler({}, None)
    assert json.loads(response["body"]) == [{"id": "minuteman", "label": "minuteman"}]


def test_tenants_list_skips_non_label_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stored objects that are not a tenant's label marker are ignored in the listing."""
    module = _tenant(monkeypatch)
    objects = {
        "tenants/minuteman/label.json": json.dumps({"label": "Minuteman"}).encode(),
        "tenants/minuteman/wan.json": b"{}",
    }
    with patch("boto3.client", return_value=fake_s3(objects)):
        response = module.lambda_handler({}, None)
    assert json.loads(response["body"]) == [{"id": "minuteman", "label": "Minuteman"}]


def test_tenant_serves_the_backbone_links(monkeypatch: pytest.MonkeyPatch) -> None:
    """The backbone-links collection of a built WAN is served from the stored document."""
    module = _tenant(monkeypatch)
    links = [{"source_name": "Minot, ND", "target_name": "Kansas City, MO"}]
    objects = {"tenants/f-35/wan.json": json.dumps({"backbone-links": links}).encode()}
    event = {
        "pathParameters": {"tenant": "f-35"},
        "path": "/x/tenants/f-35/backbone-links",
    }
    with patch("boto3.client", return_value=fake_s3(objects)):
        response = module.lambda_handler(event, None)
    assert json.loads(response["body"]) == links


def test_tenant_accepts_a_well_formed_site_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """A locations PUT whose rows carry the required fields is stored."""
    module = _tenant(monkeypatch)
    objects: dict[str, bytes] = {}
    row = {
        "name": "Site",
        "municipality": "Denver",
        "state": "CO",
        "country": "United States",
        "latitude": 1.0,
        "longitude": 2.0,
        "exemptfromdistanceconstraint": "No",
    }
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(_tenant_put("locations", [row]), None)
    assert json.loads(objects["tenants/f-35/locations.json"]) == [row]


def test_tenant_accepts_a_locations_row_with_an_extra_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A locations PUT is stored even when a row carries fields beyond the required set."""
    module = _tenant(monkeypatch)
    objects: dict[str, bytes] = {}
    row = {
        "name": "Site",
        "municipality": "Denver",
        "state": "CO",
        "country": "United States",
        "latitude": 1.0,
        "longitude": 2.0,
        "exemptfromdistanceconstraint": "No",
        "note": "extra",
    }
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(_tenant_put("locations", [row]), None)
    assert json.loads(objects["tenants/f-35/locations.json"]) == [row]


def test_tenant_rejects_a_locations_row_without_the_exempt_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A locations PUT is rejected when a row omits the exempt-from-distance-constraint field."""
    module = _tenant(monkeypatch)
    row = {
        "name": "Site",
        "municipality": "Denver",
        "state": "CO",
        "country": "United States",
        "latitude": 1.0,
        "longitude": 2.0,
    }
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler(_tenant_put("locations", [row]), None)
    assert response["statusCode"] == 400


def test_tenant_accepts_a_provider_region_without_the_exempt_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider-regions PUT does not require the exempt field that tenant locations do."""
    module = _tenant(monkeypatch)
    objects: dict[str, bytes] = {}
    row = {
        "name": "us-east-1",
        "municipality": "Ashburn",
        "state": "VA",
        "country": "United States",
        "latitude": 1.0,
        "longitude": 2.0,
    }
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(_tenant_put("provider-regions", [row]), None)
    assert json.loads(objects["tenants/f-35/provider-regions.json"]) == [row]


def test_tenant_get_serves_an_input_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """A GET on an input collection returns the whole stored document."""
    module = _tenant(monkeypatch)
    stored = {"tenants/f-35/locations.json": json.dumps({"sites": [{"id": "S"}]}).encode()}
    event = {"pathParameters": {"tenant": "f-35"}, "path": "/x/tenants/f-35/locations"}
    with patch("boto3.client", side_effect=write_clients(stored, [])):
        response = module.lambda_handler(event, None)
    assert json.loads(response["body"]) == {"sites": [{"id": "S"}]}


def test_tenant_put_persists_an_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PUT stores the input document under its own key."""
    module = _tenant(monkeypatch)
    objects: dict[str, bytes] = {}
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(_tenant_put("provider-regions", []), None)
    assert "tenants/f-35/provider-regions.json" in objects


def _stored_put(monkeypatch: pytest.MonkeyPatch, collection: str, body: Any) -> Any:
    """PUT *body* to a tenant *collection* and return the document it stored."""
    module = _tenant(monkeypatch)
    stored: dict[str, bytes] = {}
    with patch("boto3.client", side_effect=write_clients(stored, [])):
        module.lambda_handler(_tenant_put(collection, body), None)
    return json.loads(stored[f"tenants/f-35/{collection}.json"])


def test_tenant_put_persists_a_settings_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PUT to the settings resource is stored verbatim, where it was a 404 before."""
    settings = {"compass_sector_count": 4}
    assert _stored_put(monkeypatch, "settings", settings) == settings


def test_tenant_put_persists_the_forced_homes_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PUT to the forced-homes resource is stored verbatim, where it was a 404 before.

    The access tier's forced links are their own resource, so the endpoint has to accept
    one before anything writes it -- the config path they arrive on is empty today.
    """
    homes = [{"source": "Luke, AZ", "target": "Nellis, NV"}]
    assert _stored_put(monkeypatch, "forced-homes", homes) == homes


def test_tenant_put_persists_the_degree_exempt_backbone_nodes_document(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A PUT to the degree-exempt-backbone-nodes resource is stored verbatim.

    The nodes an operator holds to no diverse path count are their own resource, so the
    endpoint has to accept one before the synthesizer can read it.
    """
    exempt = ["San Jose, CA"]
    assert _stored_put(monkeypatch, "degree-exempt-backbone-nodes", exempt) == exempt


def test_tenant_rejects_a_malformed_site_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """A locations PUT whose rows lack the required fields is rejected."""
    module = _tenant(monkeypatch)
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler(_tenant_put("locations", [{"oops": 1}]), None)
    assert response["statusCode"] == 400


def test_tenant_rejects_a_non_list_site_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """An off-net PUT that is not a list of rows is rejected."""
    module = _tenant(monkeypatch)
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler(_tenant_put("off-net", {"not": "a list"}), None)
    assert response["statusCode"] == 400


def test_tenant_put_404_for_unknown_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PUT to a non-input collection is a 404."""
    module = _tenant(monkeypatch)
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler(_tenant_put("sites", {}), None)
    assert response["statusCode"] == 404


def test_tenant_put_does_not_trigger_a_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PUT only stores the input; building is a separate POST, so nothing is invoked."""
    module = _tenant(monkeypatch)
    invocations: list[dict[str, Any]] = []
    with patch("boto3.client", side_effect=write_clients({}, invocations)):
        module.lambda_handler(_tenant_put("forced-backbone-nodes", []), None)
    assert not invocations


def test_tenant_delete_removes_every_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """A DELETE removes all of the tenant's stored objects."""
    module = _tenant(monkeypatch)
    objects = {"tenants/f-35/config.json": b"{}", "tenants/f-35/wan.json": b"{}"}
    event = {"httpMethod": "DELETE", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(event, None)
    assert not objects


def test_tenant_delete_with_no_objects_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deleting a tenant with nothing stored still succeeds."""
    module = _tenant(monkeypatch)
    event = {"httpMethod": "DELETE", "pathParameters": {"tenant": "ghost"}}
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler(event, None)
    assert response["statusCode"] == 200


def test_tenant_write_404_when_no_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-GET request without a tenant is a 404."""
    module = _tenant(monkeypatch)
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler({"httpMethod": "PUT"}, None)
    assert response["statusCode"] == 404
