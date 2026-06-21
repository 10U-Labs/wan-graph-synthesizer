"""Unit tests for the per-endpoint Lambda handlers.

One file, parametrized over the read endpoints (carriers, csps, customers) and with
explicit cases for the merge and wan endpoints. Consolidated so the shared loading
and caching scaffolding lives once -- repeating it per endpoint would be duplicate
code. Each handler is loaded the way the Lambda runtime loads it (by path).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from module_utils import create_lambda_loader
from repo_utils import REPO_ROOT
from s3_store_mock import fake_ecs, fake_lambda, fake_s3


def _load(endpoint: str, monkeypatch: pytest.MonkeyPatch, **env: str) -> Any:
    """Load an endpoint's handler module with the store bucket (+ extra env) set."""
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    lambdas = REPO_ROOT / "src" / "api" / "endpoints" / endpoint / "lambdas"
    module: Any = create_lambda_loader(lambdas)("handler.py", f"{endpoint}_handler")
    module.clear_clients()
    return module


_READERS: list[dict[str, Any]] = [
    {
        "endpoint": "carriers",
        "list_keys": ["carriers/lumen.json", "carriers/zayo.json"],
        "ids": ["lumen", "zayo"],
        "stored_key": "carriers/lumen.json",
        "stored": {"vertices": [{"id": "P"}], "edges": []},
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
        "list_keys": ["csps/aws.json", "csps/azure.json"],
        "ids": ["aws", "azure"],
        "stored_key": "csps/aws.json",
        "stored": {"vertices": [{"id": "us-east"}]},
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
        "endpoint": "customers",
        "list_keys": ["customers/f-35/wan.json", "customers/joint/wan.json"],
        "ids": ["f-35", "joint"],
        "stored_key": "customers/f-35/wan.json",
        "stored": {
            "vertices": [],
            "edges": [],
            "core-nodes": [{"id": "P"}],
            "aggregation-points": [],
            "access-nodes": [],
        },
        "serve_event": {
            "pathParameters": {"customer": "f-35"},
            "path": "/x/customers/f-35/core-nodes",
        },
        "serve_expect": [{"id": "P"}],
        "unknown_event": {
            "pathParameters": {"customer": "f-35"},
            "path": "/x/customers/f-35/bogus",
        },
        "notbuilt_event": {
            "pathParameters": {"customer": "joint"},
            "path": "/x/customers/joint/edges",
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


def _carrier_graph() -> bytes:
    """A stored carrier graph (one PoP, no edges) as JSON bytes."""
    return json.dumps({"vertices": [{"id": "P"}], "edges": []}).encode()


def test_merge_post_unions_carriers(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST counts the vertices unioned from carriers (skipping non-JSON keys)."""
    module = _load("merge", monkeypatch)
    objects = {"carriers/a.json": _carrier_graph(), "carriers/b.json": _carrier_graph()}
    fake = fake_s3(objects, keys=[*objects, "carriers/_notes.txt"])
    with patch("boto3.client", return_value=fake):
        response = module.lambda_handler({"httpMethod": "POST"}, None)
    assert json.loads(response["body"]) == {"vertices": 2, "edges": 0}


def test_merge_post_stores_the_substrate(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST writes the merged substrate back to the store."""
    objects: dict[str, bytes] = {}
    module = _load("merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3(objects, keys=[])):
        module.lambda_handler({"httpMethod": "POST"}, None)
    assert "merge/substrate.json" in objects


def test_merge_get_serves_vertices(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET vertices returns the stored substrate's vertices."""
    module = _load("merge", monkeypatch)
    stored = json.dumps({"vertices": [{"id": "P"}], "edges": []}).encode()
    with patch("boto3.client", return_value=fake_s3({"merge/substrate.json": stored})):
        response = module.lambda_handler({"path": "/x/carriers/merge/vertices"}, None)
    assert json.loads(response["body"]) == [{"id": "P"}]


def test_merge_get_404_for_an_unknown_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A merge sub-resource other than vertices/edges is a 404."""
    module = _load("merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({})):
        response = module.lambda_handler({"path": "/x/carriers/merge/bogus"}, None)
    assert response["statusCode"] == 404


def test_merge_get_404_when_not_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reading the substrate before any merge returns a 'not built' 404."""
    module = _load("merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({})):
        response = module.lambda_handler({"path": "/x/carriers/merge/edges"}, None)
    assert response["statusCode"] == 404


def test_merge_caches_the_s3_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """A POST then a GET reuse the one cached client."""
    module = _load("merge", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({}, keys=[])) as mock_client:
        module.lambda_handler({"httpMethod": "POST"}, None)
        module.lambda_handler({"path": "/x/carriers/merge/vertices"}, None)
    assert mock_client.call_count == 1


def _carrier(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the carriers handler with the cascade target functions configured."""
    return _load("carriers", monkeypatch, MERGE_FUNCTION="merge-fn", WAN_FUNCTION="wan-fn")


def _carrier_clients(objects: dict[str, bytes], invocations: list[dict[str, Any]]) -> Any:
    """A boto3.client side effect handing back the S3 and Lambda fakes by service."""
    fakes = {"s3": fake_s3(objects), "lambda": fake_lambda(invocations)}
    return lambda service, **_kwargs: fakes[service]


def _put_event(carrier: str, collection: str, body: Any) -> dict[str, Any]:
    """A carrier collection PUT event."""
    return {
        "httpMethod": "PUT",
        "pathParameters": {"carrier": carrier},
        "path": f"/x/carriers/{carrier}/{collection}",
        "body": json.dumps(body),
    }


def test_carrier_put_persists_the_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PUT stores the new collection in the carrier's graph."""
    module = _carrier(monkeypatch)
    objects: dict[str, bytes] = {}
    with patch("boto3.client", side_effect=_carrier_clients(objects, [])):
        module.lambda_handler(_put_event("lumen", "vertices", [{"id": "P"}]), None)
    assert json.loads(objects["carriers/lumen.json"])["vertices"] == [{"id": "P"}]


def test_carrier_put_preserves_other_collections(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PUT keeps the carrier's other collection (read-modify-write)."""
    module = _carrier(monkeypatch)
    objects = {"carriers/lumen.json": json.dumps({"edges": [{"e": 1}]}).encode()}
    with patch("boto3.client", side_effect=_carrier_clients(objects, [])):
        module.lambda_handler(_put_event("lumen", "vertices", [{"id": "P"}]), None)
    assert json.loads(objects["carriers/lumen.json"])["edges"] == [{"e": 1}]


def test_carrier_put_cascades_to_merge_and_customers(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PUT rebuilds the substrate and each customer's WAN (merge + one per customer)."""
    module = _carrier(monkeypatch)
    invocations: list[dict[str, Any]] = []
    clients = _carrier_clients({"customers/f-35/config.json": b"{}"}, invocations)
    with patch("boto3.client", side_effect=clients):
        module.lambda_handler(_put_event("lumen", "edges", []), None)
    assert len(invocations) == 2


def test_carrier_put_404_for_unknown_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """A PUT to an unknown sub-collection is a 404."""
    module = _carrier(monkeypatch)
    with patch("boto3.client", side_effect=_carrier_clients({}, [])):
        response = module.lambda_handler(_put_event("lumen", "bogus", []), None)
    assert response["statusCode"] == 404


def test_carrier_delete_removes_the_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """A DELETE removes the carrier object (and cascades a rebuild)."""
    module = _carrier(monkeypatch)
    objects = {"carriers/lumen.json": b"{}"}
    event = {"httpMethod": "DELETE", "pathParameters": {"carrier": "lumen"}}
    with patch("boto3.client", side_effect=_carrier_clients(objects, [])):
        module.lambda_handler(event, None)
    assert "carriers/lumen.json" not in objects


def test_carrier_write_404_when_no_carrier(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-GET request without a carrier is a 404."""
    module = _carrier(monkeypatch)
    with patch("boto3.client", side_effect=_carrier_clients({}, [])):
        response = module.lambda_handler({"httpMethod": "DELETE"}, None)
    assert response["statusCode"] == 404


def _wan(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the wan handler with the create task's environment configured."""
    return _load(
        "wan",
        monkeypatch,
        CLUSTER_ARN="arn:cluster",
        TASK_DEFINITION_ARN="arn:task",
        SUBNET_ID="subnet-1",
        SECURITY_GROUP_ID="sg-1",
    )


def _wan_clients(objects: dict[str, bytes], started: list[dict[str, Any]]) -> Any:
    """A boto3.client side effect handing back the S3 and ECS fakes by service."""
    fakes = {"s3": fake_s3(objects), "ecs": fake_ecs(started)}
    return lambda service, **_kwargs: fakes[service]


def test_wan_post_returns_202(monkeypatch: pytest.MonkeyPatch) -> None:
    """Starting a create acknowledges with 202."""
    module = _wan(monkeypatch)
    event = {"httpMethod": "POST", "pathParameters": {"customer": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients({}, [])):
        response = module.lambda_handler(event, None)
    assert response["statusCode"] == 202


def test_wan_post_launches_one_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """A create launches exactly one optimizer task."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"customer": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients({}, started)):
        module.lambda_handler(event, None)
    assert len(started) == 1


def test_wan_post_marks_status_creating(monkeypatch: pytest.MonkeyPatch) -> None:
    """A create records a 'creating' status marker in the store."""
    module = _wan(monkeypatch)
    objects: dict[str, bytes] = {}
    event = {"httpMethod": "POST", "pathParameters": {"customer": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients(objects, [])):
        module.lambda_handler(event, None)
    assert "customers/f-35/wan-status.json" in objects


def test_wan_get_404_before_any_create(monkeypatch: pytest.MonkeyPatch) -> None:
    """A WAN status read before any create is a 404."""
    module = _wan(monkeypatch)
    with patch("boto3.client", side_effect=_wan_clients({}, [])):
        response = module.lambda_handler({"pathParameters": {"customer": "f-35"}}, None)
    assert response["statusCode"] == 404


def test_wan_get_200_while_creating(monkeypatch: pytest.MonkeyPatch) -> None:
    """A WAN still being created reports 200 with its status."""
    module = _wan(monkeypatch)
    objects = {"customers/f-35/wan-status.json": json.dumps({"status": "creating"}).encode()}
    with patch("boto3.client", side_effect=_wan_clients(objects, [])):
        response = module.lambda_handler({"pathParameters": {"customer": "f-35"}}, None)
    assert response["statusCode"] == 200


def test_wan_get_422_when_no_valid_wan(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed create reports 422 (no valid WAN was possible)."""
    module = _wan(monkeypatch)
    objects = {"customers/f-35/wan-status.json": json.dumps({"status": "failed"}).encode()}
    with patch("boto3.client", side_effect=_wan_clients(objects, [])):
        response = module.lambda_handler({"pathParameters": {"customer": "f-35"}}, None)
    assert response["statusCode"] == 422


def test_wan_404_when_no_customer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A request without a customer path parameter is a 404."""
    module = _wan(monkeypatch)
    with patch("boto3.client", side_effect=_wan_clients({}, [])):
        response = module.lambda_handler({}, None)
    assert response["statusCode"] == 404


def test_wan_caches_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two creates build the S3 and ECS clients once each, then reuse them."""
    module = _wan(monkeypatch)
    post = {"httpMethod": "POST", "pathParameters": {"customer": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients({}, [])) as mock_client:
        module.lambda_handler(post, None)
        module.lambda_handler(post, None)
    assert mock_client.call_count == 2
