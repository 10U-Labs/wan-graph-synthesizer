from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from test_handler_contracts import ReaderContract, load_handler, write_clients
from test_s3_store_mock import fake_s3

_LOCATIONS_ROW: dict[str, Any] = {
    "name": "Site",
    "municipality": "Denver",
    "state": "CO",
    "country": "United States",
    "latitude": 1.0,
    "longitude": 2.0,
    "exemptfromdistanceconstraint": "No",
}

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
    CFG = _READER


def _tenant(monkeypatch: pytest.MonkeyPatch) -> Any:
    return load_handler("tenants", monkeypatch)


def _tenant_put(collection: str, body: Any) -> dict[str, Any]:
    return {
        "httpMethod": "PUT",
        "pathParameters": {"tenant": "f-35"},
        "path": f"/x/tenants/f-35/{collection}",
        "body": json.dumps(body),
    }


def test_tenants_list_surfaces_each_label(monkeypatch: pytest.MonkeyPatch) -> None:
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
    module = _tenant(monkeypatch)
    with patch("boto3.client", return_value=fake_s3({"tenants/minuteman/label.json": b"{}"})):
        response = module.lambda_handler({}, None)
    assert json.loads(response["body"]) == [{"id": "minuteman", "label": "minuteman"}]


def test_tenants_list_skips_non_label_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _tenant(monkeypatch)
    objects = {
        "tenants/minuteman/label.json": json.dumps({"label": "Minuteman"}).encode(),
        "tenants/minuteman/wan.json": b"{}",
    }
    with patch("boto3.client", return_value=fake_s3(objects)):
        response = module.lambda_handler({}, None)
    assert json.loads(response["body"]) == [{"id": "minuteman", "label": "Minuteman"}]


def test_tenant_serves_the_backbone_links(monkeypatch: pytest.MonkeyPatch) -> None:
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
    module = _tenant(monkeypatch)
    objects: dict[str, bytes] = {}
    row = dict(_LOCATIONS_ROW)
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(_tenant_put("locations", [row]), None)
    assert json.loads(objects["tenants/f-35/locations.json"]) == [row]


def test_tenant_accepts_a_locations_row_with_an_extra_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _tenant(monkeypatch)
    objects: dict[str, bytes] = {}
    row = dict(_LOCATIONS_ROW, note="extra")
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(_tenant_put("locations", [row]), None)
    assert json.loads(objects["tenants/f-35/locations.json"]) == [row]


def test_tenant_rejects_a_locations_row_without_the_exempt_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    module = _tenant(monkeypatch)
    stored = {"tenants/f-35/locations.json": json.dumps({"sites": [{"id": "S"}]}).encode()}
    event = {"pathParameters": {"tenant": "f-35"}, "path": "/x/tenants/f-35/locations"}
    with patch("boto3.client", side_effect=write_clients(stored, [])):
        response = module.lambda_handler(event, None)
    assert json.loads(response["body"]) == {"sites": [{"id": "S"}]}


def test_tenant_put_persists_an_input(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _tenant(monkeypatch)
    objects: dict[str, bytes] = {}
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(_tenant_put("provider-regions", []), None)
    assert "tenants/f-35/provider-regions.json" in objects


def _stored_put(monkeypatch: pytest.MonkeyPatch, collection: str, body: Any) -> Any:
    module = _tenant(monkeypatch)
    stored: dict[str, bytes] = {}
    with patch("boto3.client", side_effect=write_clients(stored, [])):
        module.lambda_handler(_tenant_put(collection, body), None)
    return json.loads(stored[f"tenants/f-35/{collection}.json"])


def test_tenant_put_persists_a_settings_document(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = {"compass_sector_count": 4}
    assert _stored_put(monkeypatch, "settings", settings) == settings


def test_tenant_put_persists_the_forced_homes_document(monkeypatch: pytest.MonkeyPatch) -> None:
    homes = [{"source": "Luke, AZ", "target": "Nellis, NV"}]
    assert _stored_put(monkeypatch, "forced-homes", homes) == homes


def test_tenant_put_persists_the_degree_exempt_backbone_nodes_document(
        monkeypatch: pytest.MonkeyPatch) -> None:
    exempt = ["San Jose, CA"]
    assert _stored_put(monkeypatch, "degree-exempt-backbone-nodes", exempt) == exempt


def test_tenant_rejects_a_malformed_site_input(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _tenant(monkeypatch)
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler(_tenant_put("locations", [{"oops": 1}]), None)
    assert response["statusCode"] == 400


def test_tenant_rejects_a_non_list_site_input(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _tenant(monkeypatch)
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler(_tenant_put("off-net", {"not": "a list"}), None)
    assert response["statusCode"] == 400


def test_tenant_put_404_for_unknown_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _tenant(monkeypatch)
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler(_tenant_put("sites", {}), None)
    assert response["statusCode"] == 404


def test_tenant_put_does_not_trigger_a_build(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _tenant(monkeypatch)
    invocations: list[dict[str, Any]] = []
    with patch("boto3.client", side_effect=write_clients({}, invocations)):
        module.lambda_handler(_tenant_put("forced-backbone-nodes", []), None)
    assert not invocations


def test_tenant_delete_removes_every_object(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _tenant(monkeypatch)
    objects = {"tenants/f-35/config.json": b"{}", "tenants/f-35/wan.json": b"{}"}
    event = {"httpMethod": "DELETE", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=write_clients(objects, [])):
        module.lambda_handler(event, None)
    assert not objects


def test_tenant_delete_with_no_objects_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _tenant(monkeypatch)
    event = {"httpMethod": "DELETE", "pathParameters": {"tenant": "ghost"}}
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler(event, None)
    assert response["statusCode"] == 200


def test_tenant_write_404_when_no_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _tenant(monkeypatch)
    with patch("boto3.client", side_effect=write_clients({}, [])):
        response = module.lambda_handler({"httpMethod": "PUT"}, None)
    assert response["statusCode"] == 404
