from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from repo_utils import REPO_ROOT
from test_module_utils import create_lambda_loader
from test_s3_store_mock import fake_lambda, fake_s3


def load_handler(endpoint: str, monkeypatch: pytest.MonkeyPatch, **env: str) -> Any:
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    lambdas = REPO_ROOT / "src" / "api" / "endpoints" / endpoint / "lambdas"
    name = endpoint.replace("/", "_")
    module: Any = create_lambda_loader(lambdas)("handler.py", f"{name}_handler")
    module.clear_clients()
    return module


def write_clients(objects: dict[str, bytes], invocations: list[dict[str, Any]]) -> Any:
    fakes = {"s3": fake_s3(objects), "lambda": fake_lambda(invocations)}
    return lambda service, **_kwargs: fakes[service]


def write_event(cfg: dict[str, Any], collection: str, body: Any) -> dict[str, Any]:
    return {
        "httpMethod": "PUT",
        "pathParameters": {cfg["param"]: cfg["id"]},
        "path": f"/x/{cfg['endpoint']}/{cfg['id']}/{collection}",
        "body": json.dumps(body),
    }


class ReaderContract:
    CFG: dict[str, Any]

    def test_lists_the_stored_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = load_handler(self.CFG["endpoint"], monkeypatch)
        with patch("boto3.client", return_value=fake_s3({}, keys=self.CFG["list_keys"])):
            response = module.lambda_handler({}, None)
        assert json.loads(response["body"]) == self.CFG["ids"]

    def test_serves_a_stored_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = load_handler(self.CFG["endpoint"], monkeypatch)
        stored = {self.CFG["stored_key"]: json.dumps(self.CFG["stored"]).encode()}
        with patch("boto3.client", return_value=fake_s3(stored)):
            response = module.lambda_handler(self.CFG["serve_event"], None)
        assert json.loads(response["body"]) == self.CFG["serve_expect"]

    def test_404_for_an_unknown_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = load_handler(self.CFG["endpoint"], monkeypatch)
        with patch("boto3.client", return_value=fake_s3({})):
            response = module.lambda_handler(self.CFG["unknown_event"], None)
        assert response["statusCode"] == 404

    def test_404_when_the_resource_is_not_built(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = load_handler(self.CFG["endpoint"], monkeypatch)
        with patch("boto3.client", return_value=fake_s3({})):
            response = module.lambda_handler(self.CFG["notbuilt_event"], None)
        assert response["statusCode"] == 404

    def test_caches_the_s3_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = load_handler(self.CFG["endpoint"], monkeypatch)
        with patch("boto3.client", return_value=fake_s3({}, keys=[])) as mock_client:
            module.lambda_handler({}, None)
            module.lambda_handler({}, None)
        assert mock_client.call_count == 1


class SharedWriteTests:
    CFG: dict[str, Any]

    def _handler(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        return load_handler(self.CFG["endpoint"], monkeypatch)

    def _collection(self) -> str:
        return str(self.CFG["key"]).rsplit("/", 1)[-1].removesuffix(".json")

    def _put_event(self, collection: str, body: Any) -> dict[str, Any]:
        raise NotImplementedError

    def _delete_event(self) -> dict[str, Any]:
        raise NotImplementedError

    def _status_of(self, monkeypatch: pytest.MonkeyPatch, event: dict[str, Any]) -> int:
        module = self._handler(monkeypatch)
        with patch("boto3.client", side_effect=write_clients({}, [])):
            response = module.lambda_handler(event, None)
        return int(response["statusCode"])

    def _stored_after_put(self, monkeypatch: pytest.MonkeyPatch, objects: dict[str, bytes]) -> Any:
        module = self._handler(monkeypatch)
        with patch("boto3.client", side_effect=write_clients(objects, [])):
            module.lambda_handler(self._put_event(self._collection(), self.CFG["valid"]), None)
        return json.loads(objects[self.CFG["key"]])

    def test_write_persists_the_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._stored_after_put(monkeypatch, {}) == self.CFG["valid"]

    def test_write_replaces_an_existing_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stale = {self.CFG["key"]: json.dumps([{"stale": 1}]).encode()}
        assert self._stored_after_put(monkeypatch, stale) == self.CFG["valid"]

    def test_write_rejects_a_malformed_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        malformed = self._put_event(self._collection(), [{"oops": 1}])
        assert self._status_of(monkeypatch, malformed) == 400

    def test_write_rejects_a_non_list_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        malformed = self._put_event(self._collection(), {"not": "a list"})
        assert self._status_of(monkeypatch, malformed) == 400

    def test_write_404_for_unknown_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._status_of(monkeypatch, self._put_event("bogus", [])) == 404

    def test_write_does_not_trigger_a_build(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = self._handler(monkeypatch)
        invocations: list[dict[str, Any]] = []
        store = {"tenants/a/label.json": b"{}", "tenants/b/label.json": b"{}"}
        with patch("boto3.client", side_effect=write_clients(store, invocations)):
            module.lambda_handler(self._put_event(self._collection(), []), None)
        assert not invocations

    def test_delete_removes_the_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = self._handler(monkeypatch)
        objects = {self.CFG["key"]: b"{}"}
        with patch("boto3.client", side_effect=write_clients(objects, [])):
            module.lambda_handler(self._delete_event(), None)
        assert self.CFG["key"] not in objects


class WriterContract(SharedWriteTests):
    def _put_event(self, collection: str, body: Any) -> dict[str, Any]:
        return write_event(self.CFG, collection, body)

    def _delete_event(self) -> dict[str, Any]:
        return {"httpMethod": "DELETE", "pathParameters": {self.CFG["param"]: self.CFG["id"]}}

    def test_write_404_when_no_resource(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._status_of(monkeypatch, {"httpMethod": "DELETE"}) == 404


class RegionsContract(SharedWriteTests):
    def _path(self, collection: str) -> str:
        return f"/x/{self.CFG['endpoint']}/{collection}"

    def _get(self, collection: str | None = None) -> dict[str, Any]:
        return {"httpMethod": "GET", "path": self._path(collection or self._collection())}

    def _put_event(self, collection: str, body: Any) -> dict[str, Any]:
        return {
            "httpMethod": "PUT",
            "path": self._path(collection),
            "body": json.dumps(body),
        }

    def _delete_event(self) -> dict[str, Any]:
        return {"httpMethod": "DELETE", "path": self._path(self._collection())}

    def test_serves_the_stored_regions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = self._handler(monkeypatch)
        stored = {self.CFG["key"]: json.dumps(self.CFG["valid"]).encode()}
        with patch("boto3.client", return_value=fake_s3(stored)):
            response = module.lambda_handler(self._get(), None)
        assert json.loads(response["body"]) == self.CFG["valid"]

    def test_404_for_an_unknown_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = self._handler(monkeypatch)
        with patch("boto3.client", return_value=fake_s3({})):
            response = module.lambda_handler(self._get("bogus"), None)
        assert response["statusCode"] == 404

    def test_404_when_the_resource_is_not_built(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = self._handler(monkeypatch)
        with patch("boto3.client", return_value=fake_s3({})):
            response = module.lambda_handler(self._get(), None)
        assert response["statusCode"] == 404

    def test_caches_the_s3_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module = self._handler(monkeypatch)
        with patch("boto3.client", return_value=fake_s3({})) as mock_client:
            module.lambda_handler(self._get(), None)
            module.lambda_handler(self._get(), None)
        assert mock_client.call_count == 1

    def test_delete_404_for_unknown_collection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        unknown = {"httpMethod": "DELETE", "path": self._path("bogus")}
        assert self._status_of(monkeypatch, unknown) == 404
