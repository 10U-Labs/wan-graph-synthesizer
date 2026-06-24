"""Unit tests for the per-endpoint Lambda handlers.

One file, parametrized over the read endpoints (carriers, csps, tenants) and with
explicit cases for the merge and wan endpoints. Consolidated so the shared loading
and caching scaffolding lives once -- repeating it per endpoint would be duplicate
code. Each handler is loaded the way the Lambda runtime loads it (by path).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from repo_utils import REPO_ROOT
from test_module_utils import create_lambda_loader
from test_s3_store_mock import fake_ecs, fake_lambda, fake_s3


def _load(endpoint: str, monkeypatch: pytest.MonkeyPatch, **env: str) -> Any:
    """Load an endpoint's handler module with the store bucket (+ extra env) set."""
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    lambdas = REPO_ROOT / "src" / "api" / "endpoints" / endpoint / "lambdas"
    name = endpoint.replace("/", "_")
    module: Any = create_lambda_loader(lambdas)("handler.py", f"{name}_handler")
    module.clear_clients()
    return module


_READERS: list[dict[str, Any]] = [
    {
        "endpoint": "carriers",
        "list_keys": ["carriers/lumen/vertices.json", "carriers/zayo/vertices.json"],
        "ids": ["lumen", "zayo"],
        "stored_key": "carriers/lumen/vertices.json",
        "stored": [{"id": "P"}],
        "serve_event": {
            "pathParameters": {"carrier": "lumen"},
            "path": "/x/carriers/lumen/vertices",
        },
        "serve_expect": [{"id": "P"}],
        "unknown_event": {
            "pathParameters": {"carrier": "lumen"},
            "path": "/x/carriers/lumen/bogus",
        },
        "notbuilt_event": {
            "pathParameters": {"carrier": "zayo"},
            "path": "/x/carriers/zayo/edges",
        },
    },
    {
        "endpoint": "csps",
        "list_keys": ["csps/aws/vertices.json", "csps/azure/vertices.json"],
        "ids": ["aws", "azure"],
        "stored_key": "csps/aws/vertices.json",
        "stored": [{"id": "us-east"}],
        "serve_event": {
            "pathParameters": {"provider": "aws"},
            "path": "/x/csps/aws/vertices",
        },
        "serve_expect": [{"id": "us-east"}],
        "unknown_event": {
            "pathParameters": {"provider": "aws"},
            "path": "/x/csps/aws/edges",
        },
        "notbuilt_event": {
            "pathParameters": {"provider": "oci"},
            "path": "/x/csps/oci/vertices",
        },
    },
    {
        "endpoint": "tenants",
        "list_keys": ["tenants/f-35/label.json", "tenants/joint/label.json"],
        "ids": [{"id": "f-35", "label": "f-35"}, {"id": "joint", "label": "joint"}],
        "stored_key": "tenants/f-35/wan.json",
        "stored": {
            "vertices": [],
            "edges": [],
            "core-nodes": [{"id": "P"}],
            "aggregation-points": [],
            "access-nodes": [],
        },
        "serve_event": {
            "pathParameters": {"tenant": "f-35"},
            "path": "/x/tenants/f-35/core-nodes",
        },
        "serve_expect": [{"id": "P"}],
        "unknown_event": {
            "pathParameters": {"tenant": "f-35"},
            "path": "/x/tenants/f-35/bogus",
        },
        "notbuilt_event": {
            "pathParameters": {"tenant": "joint"},
            "path": "/x/tenants/joint/edges",
        },
    },
]

_READER = pytest.mark.parametrize(
    "cfg", _READERS, ids=[reader["endpoint"] for reader in _READERS]
)


@_READER
def test_lists_the_stored_ids(cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """A collection-root GET returns the stored resource ids."""
    module = _load(cfg["endpoint"], monkeypatch)
    with patch("boto3.client", return_value=fake_s3({}, keys=cfg["list_keys"])):
        response = module.lambda_handler({}, None)
    assert json.loads(response["body"]) == cfg["ids"]


@_READER
def test_serves_a_stored_collection(cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """A collection GET returns that collection from the stored graph."""
    module = _load(cfg["endpoint"], monkeypatch)
    stored = {cfg["stored_key"]: json.dumps(cfg["stored"]).encode()}
    with patch("boto3.client", return_value=fake_s3(stored)):
        response = module.lambda_handler(cfg["serve_event"], None)
    assert json.loads(response["body"]) == cfg["serve_expect"]


@_READER
def test_404_for_an_unknown_collection(
    cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown sub-collection is a 404."""
    module = _load(cfg["endpoint"], monkeypatch)
    with patch("boto3.client", return_value=fake_s3({})):
        response = module.lambda_handler(cfg["unknown_event"], None)
    assert response["statusCode"] == 404


@_READER
def test_404_when_the_resource_is_not_built(
    cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A known resource whose object is absent returns a 'not built' 404."""
    module = _load(cfg["endpoint"], monkeypatch)
    with patch("boto3.client", return_value=fake_s3({})):
        response = module.lambda_handler(cfg["notbuilt_event"], None)
    assert response["statusCode"] == 404


@_READER
def test_caches_the_s3_client(cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The second request reuses the cached client rather than rebuilding it."""
    module = _load(cfg["endpoint"], monkeypatch)
    with patch("boto3.client", return_value=fake_s3({}, keys=[])) as mock_client:
        module.lambda_handler({}, None)
        module.lambda_handler({}, None)
    assert mock_client.call_count == 1


def _merge_objects() -> dict[str, bytes]:
    """Two carriers' point/connection files: 2 points and 1 connection in total."""
    return {
        "carriers/a/vertices.json": json.dumps([{"municipality": "X"}]).encode(),
        "carriers/a/edges.json": json.dumps([{"a_municipality": "X"}]).encode(),
        "carriers/b/vertices.json": json.dumps([{"municipality": "Y"}]).encode(),
    }


def test_merge_post_unions_carriers(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST counts the points and connections unioned (and skips the merge's own output)."""
    module = _load("carriers/merge", monkeypatch)
    objects = _merge_objects()
    fake = fake_s3(objects, keys=[*objects, "carriers/merge/vertices.json"])
    with patch("boto3.client", return_value=fake):
        response = module.lambda_handler({"httpMethod": "POST"}, None)
    assert json.loads(response["body"]) == {"vertices": 2, "edges": 1}


def test_merge_post_tags_points_with_their_carrier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each merged point carries the carrier id taken from its source path."""
    module = _load("carriers/merge", monkeypatch)
    objects = _merge_objects()
    with patch("boto3.client", return_value=fake_s3(objects, keys=[*objects])):
        module.lambda_handler({"httpMethod": "POST"}, None)
    merged = json.loads(objects["carriers/merge/vertices.json"])
    assert {row["carrier"] for row in merged} == {"a", "b"}


def test_merge_post_stores_the_substrate(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST writes the merged substrate's vertices and edges back to the store."""
    objects: dict[str, bytes] = {}
    module = _load("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3(objects, keys=[])):
        module.lambda_handler({"httpMethod": "POST"}, None)
    assert "carriers/merge/vertices.json" in objects and "carriers/merge/edges.json" in objects


def test_merge_get_serves_vertices(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET vertices returns the stored substrate's vertices."""
    module = _load("carriers/merge", monkeypatch)
    stored = json.dumps([{"id": "P"}]).encode()
    with patch("boto3.client", return_value=fake_s3({"carriers/merge/vertices.json": stored})):
        response = module.lambda_handler({"path": "/x/carriers/merge/vertices"}, None)
    assert json.loads(response["body"]) == [{"id": "P"}]


def test_merge_get_404_for_an_unknown_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A merge sub-resource other than vertices/edges is a 404."""
    module = _load("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({})):
        response = module.lambda_handler({"path": "/x/carriers/merge/bogus"}, None)
    assert response["statusCode"] == 404


def test_merge_get_404_when_not_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reading the substrate before any merge returns a 'not built' 404."""
    module = _load("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({})):
        response = module.lambda_handler({"path": "/x/carriers/merge/edges"}, None)
    assert response["statusCode"] == 404


def test_merge_caches_the_s3_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """A POST then a GET reuse the one cached client."""
    module = _load("carriers/merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({}, keys=[])) as mock_client:
        module.lambda_handler({"httpMethod": "POST"}, None)
        module.lambda_handler({"path": "/x/carriers/merge/vertices"}, None)
    assert mock_client.call_count == 1


_WRITERS: list[dict[str, Any]] = [
    {
        "endpoint": "carriers",
        "param": "carrier",
        "key": "carriers/lumen/vertices.json",
        "id": "lumen",
        "env": {"MERGE_FUNCTION": "merge-fn", "WAN_FUNCTION": "wan-fn"},
        "invokes": 3,
        "valid": [{"municipality": "Denver", "state": "CO", "latitude": 1.0, "longitude": 2.0}],
    },
    {
        "endpoint": "csps",
        "param": "provider",
        "key": "csps/aws/vertices.json",
        "id": "aws",
        "env": {"WAN_FUNCTION": "wan-fn"},
        "invokes": 2,
        "valid": [{"name": "r", "municipality": "Denver", "state": "CO",
                   "latitude": 1.0, "longitude": 2.0}],
    },
]

_WRITER = pytest.mark.parametrize(
    "cfg", _WRITERS, ids=[writer["endpoint"] for writer in _WRITERS]
)


def _writer(cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load a writable endpoint's handler with its cascade env configured."""
    return _load(cfg["endpoint"], monkeypatch, **cfg["env"])


def _write_clients(objects: dict[str, bytes], invocations: list[dict[str, Any]]) -> Any:
    """A boto3.client side effect handing back the S3 and Lambda fakes by service."""
    fakes = {"s3": fake_s3(objects), "lambda": fake_lambda(invocations)}
    return lambda service, **_kwargs: fakes[service]


def _write_event(cfg: dict[str, Any], collection: str, body: Any) -> dict[str, Any]:
    """A PUT event for one of the endpoint's collections."""
    return {
        "httpMethod": "PUT",
        "pathParameters": {cfg["param"]: cfg["id"]},
        "path": f"/x/{cfg['endpoint']}/{cfg['id']}/{collection}",
        "body": json.dumps(body),
    }


@_WRITER
def test_write_persists_the_collection(
    cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PUT into an empty store stores the new vertices."""
    module = _writer(cfg, monkeypatch)
    objects: dict[str, bytes] = {}
    with patch("boto3.client", side_effect=_write_clients(objects, [])):
        module.lambda_handler(_write_event(cfg, "vertices", cfg["valid"]), None)
    assert json.loads(objects[cfg["key"]]) == cfg["valid"]


@_WRITER
def test_write_replaces_an_existing_collection(
    cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PUT over an existing collection replaces that collection's rows."""
    module = _writer(cfg, monkeypatch)
    objects = {cfg["key"]: json.dumps([{"stale": 1}]).encode()}
    with patch("boto3.client", side_effect=_write_clients(objects, [])):
        module.lambda_handler(_write_event(cfg, "vertices", cfg["valid"]), None)
    assert json.loads(objects[cfg["key"]]) == cfg["valid"]


@_WRITER
def test_write_rejects_a_malformed_row(
    cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PUT whose rows lack the required geographic fields is rejected."""
    module = _writer(cfg, monkeypatch)
    with patch("boto3.client", side_effect=_write_clients({}, [])):
        response = module.lambda_handler(_write_event(cfg, "vertices", [{"oops": 1}]), None)
    assert response["statusCode"] == 400


@_WRITER
def test_write_rejects_a_non_list_body(
    cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PUT body that is not a list of rows is rejected."""
    module = _writer(cfg, monkeypatch)
    with patch("boto3.client", side_effect=_write_clients({}, [])):
        response = module.lambda_handler(_write_event(cfg, "vertices", {"not": "a list"}), None)
    assert response["statusCode"] == 400


def test_carrier_edges_accept_the_endpoint_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    """A carrier edges PUT with the four endpoint columns is stored."""
    module = _load("carriers", monkeypatch, MERGE_FUNCTION="merge-fn", WAN_FUNCTION="wan-fn")
    objects: dict[str, bytes] = {}
    row = {"a_municipality": "A", "a_state": "X", "z_municipality": "B", "z_state": "Y"}
    with patch("boto3.client", side_effect=_write_clients(objects, [])):
        module.lambda_handler(_write_event(_WRITERS[0], "edges", [row]), None)
    assert json.loads(objects["carriers/lumen/edges.json"]) == [row]


@_WRITER
def test_write_cascades_to_dependents(
    cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PUT (re)creates the dependent graphs for every tenant."""
    module = _writer(cfg, monkeypatch)
    invocations: list[dict[str, Any]] = []
    store = {"tenants/a/label.json": b"{}", "tenants/b/label.json": b"{}"}
    with patch("boto3.client", side_effect=_write_clients(store, invocations)):
        module.lambda_handler(_write_event(cfg, "vertices", []), None)
    assert len(invocations) == cfg["invokes"]


@_WRITER
def test_write_404_for_unknown_collection(
    cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PUT to an unknown sub-collection is a 404."""
    module = _writer(cfg, monkeypatch)
    with patch("boto3.client", side_effect=_write_clients({}, [])):
        response = module.lambda_handler(_write_event(cfg, "bogus", []), None)
    assert response["statusCode"] == 404


@_WRITER
def test_delete_removes_the_object(
    cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A DELETE removes the resource object (and cascades a rebuild)."""
    module = _writer(cfg, monkeypatch)
    objects = {cfg["key"]: b"{}"}
    event = {"httpMethod": "DELETE", "pathParameters": {cfg["param"]: cfg["id"]}}
    with patch("boto3.client", side_effect=_write_clients(objects, [])):
        module.lambda_handler(event, None)
    assert cfg["key"] not in objects


@_WRITER
def test_write_404_when_no_resource(
    cfg: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-GET request without a resource id is a 404."""
    module = _writer(cfg, monkeypatch)
    with patch("boto3.client", side_effect=_write_clients({}, [])):
        response = module.lambda_handler({"httpMethod": "DELETE"}, None)
    assert response["statusCode"] == 404


def test_carrier_put_leaves_the_other_collection_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """A carrier vertices PUT writes only the vertices file, leaving edges untouched."""
    module = _load("carriers", monkeypatch, MERGE_FUNCTION="merge-fn", WAN_FUNCTION="wan-fn")
    objects = {"carriers/lumen/edges.json": json.dumps([{"e": 1}]).encode()}
    event = _write_event(_WRITERS[0], "vertices", _WRITERS[0]["valid"])
    with patch("boto3.client", side_effect=_write_clients(objects, [])):
        module.lambda_handler(event, None)
    assert json.loads(objects["carriers/lumen/edges.json"]) == [{"e": 1}]


def _tenant(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the tenants handler with the WAN-create function configured."""
    return _load("tenants", monkeypatch, WAN_FUNCTION="wan-fn")


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
        "tenants/f-35-redundant/label.json": json.dumps({"label": "F-35 (redundant)"}).encode(),
        "tenants/joint/label.json": json.dumps({"label": "Joint"}).encode(),
    }
    with patch("boto3.client", return_value=fake_s3(objects)):
        response = module.lambda_handler({}, None)
    assert json.loads(response["body"]) == [
        {"id": "f-35-redundant", "label": "F-35 (redundant)"},
        {"id": "joint", "label": "Joint"},
    ]


def test_tenants_list_falls_back_to_id_without_a_label(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tenant whose label document is empty is listed with its id as the label."""
    module = _tenant(monkeypatch)
    with patch("boto3.client", return_value=fake_s3({"tenants/joint/label.json": b"{}"})):
        response = module.lambda_handler({}, None)
    assert json.loads(response["body"]) == [{"id": "joint", "label": "joint"}]


def test_tenant_get_serves_an_input_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """A GET on an input collection returns the whole stored document."""
    module = _tenant(monkeypatch)
    stored = {"tenants/f-35/locations.json": json.dumps({"vertices": [{"id": "S"}]}).encode()}
    event = {"pathParameters": {"tenant": "f-35"}, "path": "/x/tenants/f-35/locations"}
    with patch("boto3.client", side_effect=_write_clients(stored, [])):
        response = module.lambda_handler(event, None)
    assert json.loads(response["body"]) == {"vertices": [{"id": "S"}]}


def test_tenant_put_persists_an_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PUT stores the input document under its own key."""
    module = _tenant(monkeypatch)
    objects: dict[str, bytes] = {}
    with patch("boto3.client", side_effect=_write_clients(objects, [])):
        module.lambda_handler(_tenant_put("csp-regions", []), None)
    assert "tenants/f-35/csp-regions.json" in objects


def test_tenant_rejects_a_malformed_vertex_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """A locations PUT whose rows lack the required fields is rejected."""
    module = _tenant(monkeypatch)
    with patch("boto3.client", side_effect=_write_clients({}, [])):
        response = module.lambda_handler(_tenant_put("locations", [{"oops": 1}]), None)
    assert response["statusCode"] == 400


def test_tenant_rejects_a_non_list_vertex_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """An off-net PUT that is not a list of rows is rejected."""
    module = _tenant(monkeypatch)
    with patch("boto3.client", side_effect=_write_clients({}, [])):
        response = module.lambda_handler(_tenant_put("off-net", {"not": "a list"}), None)
    assert response["statusCode"] == 400


def test_tenant_put_404_for_unknown_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PUT to a non-input collection is a 404."""
    module = _tenant(monkeypatch)
    with patch("boto3.client", side_effect=_write_clients({}, [])):
        response = module.lambda_handler(_tenant_put("vertices", {}), None)
    assert response["statusCode"] == 404


def test_tenant_put_recreates_the_wan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each input PUT re-creates the WAN (two PUTs reuse the cached client)."""
    module = _tenant(monkeypatch)
    invocations: list[dict[str, Any]] = []
    with patch("boto3.client", side_effect=_write_clients({}, invocations)):
        module.lambda_handler(_tenant_put("forced-core-nodes", []), None)
        module.lambda_handler(_tenant_put("forced-core-nodes", []), None)
    assert len(invocations) == 2


def test_tenant_delete_removes_every_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """A DELETE removes all of the tenant's stored objects."""
    module = _tenant(monkeypatch)
    objects = {"tenants/f-35/config.json": b"{}", "tenants/f-35/wan.json": b"{}"}
    event = {"httpMethod": "DELETE", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=_write_clients(objects, [])):
        module.lambda_handler(event, None)
    assert not objects


def test_tenant_delete_with_no_objects_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deleting a tenant with nothing stored still succeeds."""
    module = _tenant(monkeypatch)
    event = {"httpMethod": "DELETE", "pathParameters": {"tenant": "ghost"}}
    with patch("boto3.client", side_effect=_write_clients({}, [])):
        response = module.lambda_handler(event, None)
    assert response["statusCode"] == 200


def test_tenant_write_404_when_no_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-GET request without a tenant is a 404."""
    module = _tenant(monkeypatch)
    with patch("boto3.client", side_effect=_write_clients({}, [])):
        response = module.lambda_handler({"httpMethod": "PUT"}, None)
    assert response["statusCode"] == 404


def _wan(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the wan handler with the create task's environment configured."""
    return _load(
        "tenants/wan",
        monkeypatch,
        CLUSTER_ARN="arn:cluster",
        TASK_DEFINITION_ARN="arn:task",
        SUBNET_ID="subnet-1",
        SECURITY_GROUP_ID="sg-1",
    )


def _wan_clients(
    objects: dict[str, bytes],
    started: list[dict[str, Any]],
    task_tags: dict[str, str] | None = None,
) -> Any:
    """A boto3.client side effect handing back the S3 and ECS fakes by service."""
    fakes = {"s3": fake_s3(objects), "ecs": fake_ecs(started, task_tags)}
    return lambda service, **_kwargs: fakes[service]


def _stopped_event(
    stop_code: str = "SpotInterruption",
    reason: str = "Your Spot Task was interrupted.",
    last_status: str = "STOPPED",
) -> dict[str, Any]:
    """An EventBridge ECS Task State Change event for the synthesizer cluster."""
    return {
        "source": "aws.ecs",
        "detail-type": "ECS Task State Change",
        "detail": {
            "lastStatus": last_status,
            "stopCode": stop_code,
            "stoppedReason": reason,
            "taskArn": "arn:aws:ecs:task/abc",
            "clusterArn": "arn:cluster",
        },
    }


def test_wan_post_returns_202(monkeypatch: pytest.MonkeyPatch) -> None:
    """Starting a create acknowledges with 202."""
    module = _wan(monkeypatch)
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients({}, [])):
        response = module.lambda_handler(event, None)
    assert response["statusCode"] == 202


def test_wan_post_launches_one_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """A create launches exactly one synthesizer task."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients({}, started)):
        module.lambda_handler(event, None)
    assert len(started) == 1


def test_wan_post_launches_on_spot(monkeypatch: pytest.MonkeyPatch) -> None:
    """The create runs on Fargate Spot for cost (interruptions are recovered)."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients({}, started)):
        module.lambda_handler(event, None)
    assert started[0]["capacityProviderStrategy"][0]["capacityProvider"] == "FARGATE_SPOT"


def test_wan_post_tags_task_for_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first attempt is tagged Tenant + Attempt 1 so a reclaim can be relaunched."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients({}, started)):
        module.lambda_handler(event, None)
    assert started[0]["tags"] == [
        {"key": "Tenant", "value": "f-35"},
        {"key": "Attempt", "value": "1"},
    ]


def test_spot_interruption_relaunches_with_next_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Spot-interrupted build relaunches for the same tenant at the next attempt."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    tags = {"Tenant": "f-35", "Attempt": "1"}
    with patch("boto3.client", side_effect=_wan_clients({}, started, tags)):
        module.lambda_handler(_stopped_event(), None)
    assert started[0]["tags"] == [
        {"key": "Tenant", "value": "f-35"},
        {"key": "Attempt", "value": "2"},
    ]


def test_spot_interruption_past_cap_marks_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Past the attempt cap the build is recorded failed instead of relaunched again."""
    module = _wan(monkeypatch)
    objects: dict[str, bytes] = {}
    started: list[dict[str, Any]] = []
    tags = {"Tenant": "f-35", "Attempt": str(module.MAX_ATTEMPTS)}
    with patch("boto3.client", side_effect=_wan_clients(objects, started, tags)):
        module.lambda_handler(_stopped_event(), None)
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "failed"


def test_non_spot_stop_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A normal (non-Spot) task stop is not relaunched."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    event = _stopped_event(stop_code="EssentialContainerExited", reason="container exited")
    with patch("boto3.client", side_effect=_wan_clients({}, started, {"Tenant": "f-35"})):
        module.lambda_handler(event, None)
    assert not started


def test_running_task_event_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-STOPPED task-state event is ignored."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    with patch("boto3.client", side_effect=_wan_clients({}, started, {"Tenant": "f-35"})):
        result = module.lambda_handler(_stopped_event(last_status="RUNNING"), None)
    assert result["handled"] is False


def test_stop_of_unknown_task_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Spot stop of a task with no Tenant tag (or already gone) is not relaunched."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    with patch("boto3.client", side_effect=_wan_clients({}, started, None)):
        module.lambda_handler(_stopped_event(), None)
    assert not started


def test_stop_without_tenant_tag_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Spot stop of a tagged-but-not-ours task is not relaunched."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    with patch("boto3.client", side_effect=_wan_clients({}, started, {"Other": "x"})):
        module.lambda_handler(_stopped_event(), None)
    assert not started


def test_wan_post_marks_status_creating(monkeypatch: pytest.MonkeyPatch) -> None:
    """A create records a 'creating' status marker in the store."""
    module = _wan(monkeypatch)
    objects: dict[str, bytes] = {}
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients(objects, [])):
        module.lambda_handler(event, None)
    assert "tenants/f-35/wan-status.json" in objects


def test_wan_get_404_before_any_create(monkeypatch: pytest.MonkeyPatch) -> None:
    """A WAN status read before any create is a 404."""
    module = _wan(monkeypatch)
    with patch("boto3.client", side_effect=_wan_clients({}, [])):
        response = module.lambda_handler({"pathParameters": {"tenant": "f-35"}}, None)
    assert response["statusCode"] == 404


def test_wan_get_200_while_creating(monkeypatch: pytest.MonkeyPatch) -> None:
    """A WAN still being created reports 200 with its status."""
    module = _wan(monkeypatch)
    objects = {"tenants/f-35/wan-status.json": json.dumps({"status": "creating"}).encode()}
    with patch("boto3.client", side_effect=_wan_clients(objects, [])):
        response = module.lambda_handler({"pathParameters": {"tenant": "f-35"}}, None)
    assert response["statusCode"] == 200


def test_wan_get_422_when_no_valid_wan(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed create reports 422 (no valid WAN was possible)."""
    module = _wan(monkeypatch)
    objects = {"tenants/f-35/wan-status.json": json.dumps({"status": "failed"}).encode()}
    with patch("boto3.client", side_effect=_wan_clients(objects, [])):
        response = module.lambda_handler({"pathParameters": {"tenant": "f-35"}}, None)
    assert response["statusCode"] == 422


def test_wan_404_when_no_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """A request without a tenant path parameter is a 404."""
    module = _wan(monkeypatch)
    with patch("boto3.client", side_effect=_wan_clients({}, [])):
        response = module.lambda_handler({}, None)
    assert response["statusCode"] == 404


def test_wan_caches_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two creates build the S3 and ECS clients once each, then reuse them."""
    module = _wan(monkeypatch)
    post = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients({}, [])) as mock_client:
        module.lambda_handler(post, None)
        module.lambda_handler(post, None)
    assert mock_client.call_count == 2
