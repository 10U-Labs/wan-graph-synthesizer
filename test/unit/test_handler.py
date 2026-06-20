"""Unit tests for the read Lambda handler (serves graph JSON from the S3 store)."""

from __future__ import annotations

import json
import types
from typing import Any

import pytest

import fixtures
from api import handler
from wan_designer import graph_collections as gc
from wan_designer.output import design_payload


class _NoSuchKey(Exception):
    """Stand-in for the S3 client's NoSuchKey exception."""


def _fake_store(objects: dict[str, bytes]) -> Any:
    """A stand-in S3 client: serves canned objects, raises NoSuchKey otherwise."""

    def get_object(**kwargs: Any) -> dict[str, Any]:
        """Return a canned object body, or raise NoSuchKey when absent."""
        key = kwargs["Key"]
        if key not in objects:
            raise _NoSuchKey()
        return {"Body": types.SimpleNamespace(read=lambda: objects[key])}

    return types.SimpleNamespace(
        get_object=get_object,
        exceptions=types.SimpleNamespace(NoSuchKey=_NoSuchKey),
    )


def _carrier_object() -> bytes:
    """A stored carrier input graph (vertices + edges) as JSON bytes."""
    graph = gc.input_graph(fixtures.ring_vertices(), fixtures.ring_physical_edges())
    return json.dumps(graph).encode()


def _customer_object() -> bytes:
    """A stored customer WAN design payload as JSON bytes."""
    payload = design_payload(fixtures.sample_sources(), fixtures.ring_artifacts())
    return json.dumps(payload).encode()


@pytest.fixture(autouse=True)
def _store_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the handler at a test bucket name for every test."""
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")


def _event(proxy: str) -> dict[str, Any]:
    """An API Gateway proxy event for the given path suffix."""
    return {"pathParameters": {"proxy": proxy}}


def test_dispatch_serves_a_carrier_collection() -> None:
    """A carrier vertices request returns the stored carrier graph's vertices."""
    store = _fake_store({"carriers/lumen.json": _carrier_object()})
    response = handler.dispatch(_event("carriers/lumen/vertices"), store)
    assert response["statusCode"] == 200


def test_dispatch_serves_a_customer_tier() -> None:
    """A customer core-nodes request slices the stored WAN's tier view."""
    store = _fake_store({"customers/f-35.json": _customer_object()})
    response = handler.dispatch(_event("customers/f-35/core-nodes"), store)
    assert response["statusCode"] == 200


def test_dispatch_returns_404_for_an_unknown_collection() -> None:
    """A known resource with an unknown collection is a 404, not a 500."""
    store = _fake_store({"customers/f-35.json": _customer_object()})
    response = handler.dispatch(_event("customers/f-35/bogus"), store)
    assert response["statusCode"] == 404


def test_dispatch_returns_404_for_a_malformed_path() -> None:
    """A path that is not exactly resource/name/collection is a 404."""
    response = handler.dispatch(_event("carriers/lumen"), _fake_store({}))
    assert response["statusCode"] == 404


def test_dispatch_returns_404_when_the_graph_is_not_built() -> None:
    """A known route whose object is absent returns a 'not built' 404."""
    response = handler.dispatch(_event("carriers/zayo/vertices"), _fake_store({}))
    assert response["statusCode"] == 404


def test_handler_constructs_a_client_then_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Lambda entry point builds the real client and delegates to dispatch."""
    monkeypatch.setattr(handler, "dispatch", lambda event, _store: {"seen": event})
    result = handler.handler(_event("carriers/lumen/vertices"), None)
    assert result == {"seen": _event("carriers/lumen/vertices")}
