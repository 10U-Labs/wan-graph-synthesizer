"""Shared handler-test scaffolding and the read/write endpoint contracts.

The carrier, data-center and tenant handlers are built on one uniform read/write
framework, so their unit tests are identical bar the endpoint's data. The providers
endpoint stores a single fixed object (no id, no listing), so it has its own
:class:`RegionsContract`. To keep each endpoint's
``test_handler.py`` free of cross-file duplicate code (which the test pylint's R0801
compares across all of ``test/``), the shared loader, the fake-client wiring and the
parametric test bodies live here once. An endpoint test subclasses ``ReaderContract``
/ ``WriterContract`` and sets ``CFG``; pytest collects the inherited tests under the
subclass. This module is not collected itself (its name is not ``test_*``).

The write side is the same behaviour whichever way a resource is addressed, so it
lives once in :class:`WriteBehaviour` and each contract supplies only the events its
endpoint answers to: by path parameter where a resource has an id, by path alone
where the endpoint stores one fixed object.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from repo_utils import REPO_ROOT
from test_module_utils import create_lambda_loader
from test_s3_store_mock import fake_lambda, fake_s3


def load_handler(endpoint: str, monkeypatch: pytest.MonkeyPatch, **env: str) -> Any:
    """Load an endpoint's handler module with the store bucket (+ extra env) set.

    Every endpoint keeps its handler at the flat ``lambdas/handler.py``.
    """
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    lambdas = REPO_ROOT / "src" / "api" / "endpoints" / endpoint / "lambdas"
    name = endpoint.replace("/", "_")
    module: Any = create_lambda_loader(lambdas)("handler.py", f"{name}_handler")
    module.clear_clients()
    return module


def write_clients(objects: dict[str, bytes], invocations: list[dict[str, Any]]) -> Any:
    """A boto3.client side effect handing back the S3 and Lambda fakes by service."""
    fakes = {"s3": fake_s3(objects), "lambda": fake_lambda(invocations)}
    return lambda service, **_kwargs: fakes[service]


def write_event(cfg: dict[str, Any], collection: str, body: Any) -> dict[str, Any]:
    """A PUT event for one of the endpoint's collections."""
    return {
        "httpMethod": "PUT",
        "pathParameters": {cfg["param"]: cfg["id"]},
        "path": f"/x/{cfg['endpoint']}/{cfg['id']}/{collection}",
        "body": json.dumps(body),
    }


class ReaderContract:
    """The read-side tests shared by the carrier, data-center and tenant endpoints.

    A subclass sets ``CFG`` to the endpoint's listing keys, ids and sample events.
    """

    CFG: dict[str, Any]

    def test_lists_the_stored_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A collection-root GET returns the stored resource ids."""
        module = load_handler(self.CFG["endpoint"], monkeypatch)
        with patch("boto3.client", return_value=fake_s3({}, keys=self.CFG["list_keys"])):
            response = module.lambda_handler({}, None)
        assert json.loads(response["body"]) == self.CFG["ids"]

    def test_serves_a_stored_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A collection GET returns that collection from the stored graph."""
        module = load_handler(self.CFG["endpoint"], monkeypatch)
        stored = {self.CFG["stored_key"]: json.dumps(self.CFG["stored"]).encode()}
        with patch("boto3.client", return_value=fake_s3(stored)):
            response = module.lambda_handler(self.CFG["serve_event"], None)
        assert json.loads(response["body"]) == self.CFG["serve_expect"]

    def test_404_for_an_unknown_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unknown sub-collection is a 404."""
        module = load_handler(self.CFG["endpoint"], monkeypatch)
        with patch("boto3.client", return_value=fake_s3({})):
            response = module.lambda_handler(self.CFG["unknown_event"], None)
        assert response["statusCode"] == 404

    def test_404_when_the_resource_is_not_built(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A known resource whose object is absent returns a 'not built' 404."""
        module = load_handler(self.CFG["endpoint"], monkeypatch)
        with patch("boto3.client", return_value=fake_s3({})):
            response = module.lambda_handler(self.CFG["notbuilt_event"], None)
        assert response["statusCode"] == 404

    def test_caches_the_s3_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The second request reuses the cached client rather than rebuilding it."""
        module = load_handler(self.CFG["endpoint"], monkeypatch)
        with patch("boto3.client", return_value=fake_s3({}, keys=[])) as mock_client:
            module.lambda_handler({}, None)
            module.lambda_handler({}, None)
        assert mock_client.call_count == 1


class WriteBehaviour:
    """The write-side tests every storing endpoint shares.

    A subclass supplies the two events its endpoint is addressed by -- a PUT to one of
    its collections and the DELETE that removes what it stores -- and sets ``CFG`` to
    the endpoint's name, stored key and a valid row. Everything the handlers do with
    those events is the same, so it is written once here.
    """

    CFG: dict[str, Any]

    def _handler(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        """Load the endpoint's handler."""
        return load_handler(self.CFG["endpoint"], monkeypatch)

    def _put_event(self, collection: str, body: Any) -> dict[str, Any]:
        """A PUT event for one of the endpoint's collections."""
        raise NotImplementedError

    def _delete_event(self) -> dict[str, Any]:
        """The DELETE event that removes what the endpoint stores."""
        raise NotImplementedError

    def _status_of(self, monkeypatch: pytest.MonkeyPatch, event: dict[str, Any]) -> int:
        """The status the handler answers ``event`` with, against an empty store."""
        module = self._handler(monkeypatch)
        with patch("boto3.client", side_effect=write_clients({}, [])):
            response = module.lambda_handler(event, None)
        return int(response["statusCode"])

    def _stored_after_put(self, monkeypatch: pytest.MonkeyPatch, objects: dict[str, bytes]) -> Any:
        """PUT the endpoint's valid rows over ``objects`` and read back what it stored."""
        module = self._handler(monkeypatch)
        with patch("boto3.client", side_effect=write_clients(objects, [])):
            module.lambda_handler(self._put_event("vertices", self.CFG["valid"]), None)
        return json.loads(objects[self.CFG["key"]])

    def test_write_persists_the_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A PUT into an empty store stores the new vertices."""
        assert self._stored_after_put(monkeypatch, {}) == self.CFG["valid"]

    def test_write_replaces_an_existing_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A PUT over an existing collection replaces that collection's rows."""
        stale = {self.CFG["key"]: json.dumps([{"stale": 1}]).encode()}
        assert self._stored_after_put(monkeypatch, stale) == self.CFG["valid"]

    def test_write_rejects_a_malformed_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A PUT whose rows lack the required geographic fields is rejected."""
        assert self._status_of(monkeypatch, self._put_event("vertices", [{"oops": 1}])) == 400

    def test_write_rejects_a_non_list_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A PUT body that is not a list of rows is rejected."""
        malformed = self._put_event("vertices", {"not": "a list"})
        assert self._status_of(monkeypatch, malformed) == 400

    def test_write_404_for_unknown_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A PUT to an unknown sub-collection is a 404."""
        assert self._status_of(monkeypatch, self._put_event("bogus", [])) == 404

    def test_write_does_not_trigger_a_build(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A PUT only stores the collection; building is a separate POST, so nothing is invoked."""
        module = self._handler(monkeypatch)
        invocations: list[dict[str, Any]] = []
        store = {"tenants/a/label.json": b"{}", "tenants/b/label.json": b"{}"}
        with patch("boto3.client", side_effect=write_clients(store, invocations)):
            module.lambda_handler(self._put_event("vertices", []), None)
        assert not invocations

    def test_delete_removes_the_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A DELETE removes the stored object."""
        module = self._handler(monkeypatch)
        objects = {self.CFG["key"]: b"{}"}
        with patch("boto3.client", side_effect=write_clients(objects, [])):
            module.lambda_handler(self._delete_event(), None)
        assert self.CFG["key"] not in objects


class WriterContract(WriteBehaviour):
    """The write side as the carrier and data-center endpoints are addressed.

    Their resources carry an id, so a request names it in a path parameter and a DELETE
    removes the whole resource. A subclass sets ``CFG`` to the endpoint's key, id and a
    valid row.
    """

    def _put_event(self, collection: str, body: Any) -> dict[str, Any]:
        """A PUT to one of the resource's collections, addressed by its id."""
        return write_event(self.CFG, collection, body)

    def _delete_event(self) -> dict[str, Any]:
        """A DELETE of the whole resource, addressed by its id."""
        return {"httpMethod": "DELETE", "pathParameters": {self.CFG["param"]: self.CFG["id"]}}

    def test_write_404_when_no_resource(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-GET request without a resource id is a 404."""
        assert self._status_of(monkeypatch, {"httpMethod": "DELETE"}) == 404


class RegionsContract(WriteBehaviour):
    """Read/write tests for the single-resource providers endpoint.

    Unlike the id-keyed framework endpoints, the providers endpoint stores one fixed
    object (its regions), so there is no id path parameter and no listing: a request
    names the collection in its path and nothing else. A subclass sets ``CFG`` to the
    endpoint name, its stored key, and a valid row.
    """

    def _path(self, collection: str) -> str:
        """The request path addressing one of the endpoint's collections."""
        return f"/x/{self.CFG['endpoint']}/{collection}"

    def _get(self, collection: str = "vertices") -> dict[str, Any]:
        """A GET event for one of the endpoint's collections."""
        return {"httpMethod": "GET", "path": self._path(collection)}

    def _put_event(self, collection: str, body: Any) -> dict[str, Any]:
        """A PUT to one of the endpoint's collections, addressed by path."""
        return {
            "httpMethod": "PUT",
            "path": self._path(collection),
            "body": json.dumps(body),
        }

    def _delete_event(self) -> dict[str, Any]:
        """A DELETE of the stored regions, addressed by path."""
        return {"httpMethod": "DELETE", "path": self._path("vertices")}

    def test_serves_the_stored_regions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A vertices GET returns the stored regions."""
        module = self._handler(monkeypatch)
        stored = {self.CFG["key"]: json.dumps(self.CFG["valid"]).encode()}
        with patch("boto3.client", return_value=fake_s3(stored)):
            response = module.lambda_handler(self._get(), None)
        assert json.loads(response["body"]) == self.CFG["valid"]

    def test_404_for_an_unknown_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unknown sub-collection is a 404."""
        module = self._handler(monkeypatch)
        with patch("boto3.client", return_value=fake_s3({})):
            response = module.lambda_handler(self._get("edges"), None)
        assert response["statusCode"] == 404

    def test_404_when_the_resource_is_not_built(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A vertices GET with no stored object returns a 'not built' 404."""
        module = self._handler(monkeypatch)
        with patch("boto3.client", return_value=fake_s3({})):
            response = module.lambda_handler(self._get(), None)
        assert response["statusCode"] == 404

    def test_caches_the_s3_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The second request reuses the cached client rather than rebuilding it."""
        module = self._handler(monkeypatch)
        with patch("boto3.client", return_value=fake_s3({})) as mock_client:
            module.lambda_handler(self._get(), None)
            module.lambda_handler(self._get(), None)
        assert mock_client.call_count == 1

    def test_delete_404_for_unknown_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A DELETE of an unknown sub-collection is a 404."""
        unknown = {"httpMethod": "DELETE", "path": self._path("bogus")}
        assert self._status_of(monkeypatch, unknown) == 404
