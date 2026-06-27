"""Shared handler-test scaffolding and the read/write endpoint contracts.

The carrier, CSP and tenant handlers are built on one uniform read/write framework,
so their unit tests are identical bar the endpoint's data. To keep each endpoint's
``test_handler.py`` free of cross-file duplicate code (which the test pylint's R0801
compares across all of ``test/``), the shared loader, the fake-client wiring and the
parametric test bodies live here once. An endpoint test subclasses ``ReaderContract``
/ ``WriterContract`` and sets ``CFG``; pytest collects the inherited tests under the
subclass. This module is not collected itself (its name is not ``test_*``).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from repo_utils import REPO_ROOT
from test_module_utils import create_lambda_loader
from test_s3_store_mock import fake_lambda, fake_s3


def load_handler(
    endpoint: str, monkeypatch: pytest.MonkeyPatch, subdir: str = "", **env: str
) -> Any:
    """Load an endpoint's handler module with the store bucket (+ extra env) set.

    ``subdir`` names a folder under ``lambdas/`` when an endpoint groups its handler by
    role (the wan endpoint's dispatcher lives at ``lambdas/endpoint/handler.py``); it
    defaults to the flat ``lambdas/handler.py`` the other endpoints use.
    """
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    lambdas = REPO_ROOT / "src" / "api" / "endpoints" / endpoint / "lambdas"
    if subdir:
        lambdas = lambdas / subdir
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
    """The read-side tests shared by the carrier, CSP and tenant endpoints.

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


class WriterContract:
    """The write-side tests shared by the carrier and CSP endpoints.

    A subclass sets ``CFG`` to the endpoint's key, id and a valid row.
    """

    CFG: dict[str, Any]

    def _writer(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        """Load the endpoint's handler."""
        return load_handler(self.CFG["endpoint"], monkeypatch)

    def test_write_persists_the_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A PUT into an empty store stores the new vertices."""
        module = self._writer(monkeypatch)
        objects: dict[str, bytes] = {}
        with patch("boto3.client", side_effect=write_clients(objects, [])):
            module.lambda_handler(write_event(self.CFG, "vertices", self.CFG["valid"]), None)
        assert json.loads(objects[self.CFG["key"]]) == self.CFG["valid"]

    def test_write_replaces_an_existing_collection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A PUT over an existing collection replaces that collection's rows."""
        module = self._writer(monkeypatch)
        objects = {self.CFG["key"]: json.dumps([{"stale": 1}]).encode()}
        with patch("boto3.client", side_effect=write_clients(objects, [])):
            module.lambda_handler(write_event(self.CFG, "vertices", self.CFG["valid"]), None)
        assert json.loads(objects[self.CFG["key"]]) == self.CFG["valid"]

    def test_write_rejects_a_malformed_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A PUT whose rows lack the required geographic fields is rejected."""
        module = self._writer(monkeypatch)
        with patch("boto3.client", side_effect=write_clients({}, [])):
            response = module.lambda_handler(write_event(self.CFG, "vertices", [{"oops": 1}]), None)
        assert response["statusCode"] == 400

    def test_write_rejects_a_non_list_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A PUT body that is not a list of rows is rejected."""
        module = self._writer(monkeypatch)
        with patch("boto3.client", side_effect=write_clients({}, [])):
            response = module.lambda_handler(
                write_event(self.CFG, "vertices", {"not": "a list"}), None
            )
        assert response["statusCode"] == 400

    def test_write_does_not_trigger_a_build(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A PUT only stores the collection; building is a separate POST, so nothing is invoked."""
        module = self._writer(monkeypatch)
        invocations: list[dict[str, Any]] = []
        store = {"tenants/a/label.json": b"{}", "tenants/b/label.json": b"{}"}
        with patch("boto3.client", side_effect=write_clients(store, invocations)):
            module.lambda_handler(write_event(self.CFG, "vertices", []), None)
        assert not invocations

    def test_write_404_for_unknown_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A PUT to an unknown sub-collection is a 404."""
        module = self._writer(monkeypatch)
        with patch("boto3.client", side_effect=write_clients({}, [])):
            response = module.lambda_handler(write_event(self.CFG, "bogus", []), None)
        assert response["statusCode"] == 404

    def test_delete_removes_the_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A DELETE removes the resource object."""
        module = self._writer(monkeypatch)
        objects = {self.CFG["key"]: b"{}"}
        event = {"httpMethod": "DELETE", "pathParameters": {self.CFG["param"]: self.CFG["id"]}}
        with patch("boto3.client", side_effect=write_clients(objects, [])):
            module.lambda_handler(event, None)
        assert self.CFG["key"] not in objects

    def test_write_404_when_no_resource(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-GET request without a resource id is a 404."""
        module = self._writer(monkeypatch)
        with patch("boto3.client", side_effect=write_clients({}, [])):
            response = module.lambda_handler({"httpMethod": "DELETE"}, None)
        assert response["statusCode"] == 404
