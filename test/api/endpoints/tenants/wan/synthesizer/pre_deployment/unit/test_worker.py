"""Unit tests for the synthesizer worker Lambda.

The heavy design pipeline is stubbed (it is exercised by the synthesizer tests);
these tests cover the worker's own orchestration and S3 I/O: it reads the tenant from
the invoke event, moves the status to ``building``, and publishes ``ready``/``failed``.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from repo_utils import REPO_ROOT
from test_module_utils import load_module_from_path
from test_s3_store_mock import fake_s3
from synthesizer.input_graph import Vertex
from synthesizer.model import DesignParams

_PATH = REPO_ROOT / "src/api/endpoints/tenants/wan/lambdas/synthesizer/handler.py"


@pytest.fixture(name="worker")
def worker_fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the synthesizer worker with the store bucket configured."""
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    return load_module_from_path("synthesizer_worker", _PATH)


def _stub_pipeline(module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the heavy design pipeline with light canned stand-ins."""
    pop = Vertex(id="P", name="P", kind="PoP", coords=(0.0, 0.0))
    site = Vertex(id="S", name="S", kind="Tenant site", coords=(1.0, 1.0))
    graph = [pop, site]
    config = SimpleNamespace(
        params=DesignParams(),
        forced_connections=(),
        excluded_connections=(),
    )
    payload = {
        "vertices": [{"id": "P", "tier_role": "backbone"}],
        "access_edges": [],
        "physical_edges": [],
    }
    monkeypatch.setattr(module, "load_substrate", lambda *_a: (graph, {}))
    monkeypatch.setattr(module, "load_sites", lambda _p: [])
    monkeypatch.setattr(module, "load_regions", lambda _p: [])
    monkeypatch.setattr(module, "load_off_net", lambda _p: [])
    monkeypatch.setattr(module, "app_config_from_parts", lambda _p: config)
    monkeypatch.setattr(module, "dual_home", lambda *_a: (graph, {}))
    monkeypatch.setattr(module, "apply_role_overrides", lambda *_a: (graph, {}, object()))
    monkeypatch.setattr(module, "synthesize_two_tier_design", lambda *_a: object())
    monkeypatch.setattr(module, "finalize", lambda *_a: (graph, {}, object(), {}))
    monkeypatch.setattr(module, "design_payload", lambda *_a: payload)


def _inputs(module: Any) -> dict[str, bytes]:
    """Every object the worker reads (content unused; pipeline stubbed)."""
    keys = [
        "carriers/merge/vertices.json",
        "carriers/merge/edges.json",
        "data-centers/merge/vertices.json",
        "tenants/f-35/locations.json",
        "tenants/f-35/csp-regions.json",
        "tenants/f-35/off-net.json",
    ]
    keys += [f"tenants/f-35/{resource}.json" for resource in module.CONFIG_RESOURCES]
    return {key: b"[]" for key in keys}


def _run(module: Any, monkeypatch: pytest.MonkeyPatch, fail: bool = False) -> dict[str, bytes]:
    """Stub the pipeline (optionally failing the synthesize), run the worker, return the store."""
    _stub_pipeline(module, monkeypatch)
    if fail:

        def _raise(*_args: Any) -> Any:
            raise ValueError("No feasible design")

        monkeypatch.setattr(module, "synthesize_two_tier_design", _raise)
    objects = _inputs(module)
    with patch("boto3.client", return_value=fake_s3(objects)):
        module.lambda_handler({"tenant": "f-35"}, None)
    return objects


def test_publishes_the_wan_on_success(worker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful build writes the tenant's WAN JSON to the store."""
    objects = _run(worker, monkeypatch)
    assert "tenants/f-35/wan.json" in objects


def test_marks_status_ready_on_success(worker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful build records a 'ready' status."""
    objects = _run(worker, monkeypatch)
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "ready"


def test_records_failed_when_no_valid_wan(worker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the synthesizer reports infeasibility, the status is recorded as failed."""
    objects = _run(worker, monkeypatch, fail=True)
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "failed"


def test_reads_the_tenant_from_the_event(worker: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The worker builds the tenant named in the invoke event."""
    _stub_pipeline(worker, monkeypatch)
    objects = _inputs(worker)
    with patch("boto3.client", return_value=fake_s3(objects)):
        worker.lambda_handler({"tenant": "f-35"}, None)
    assert "tenants/f-35/wan.json" in objects


def test_logs_progress_at_info(
    worker: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A run emits INFO progress so a long build is observable, not silent."""
    with caplog.at_level(logging.INFO):
        _run(worker, monkeypatch)
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "f-35" in messages and "Publishing" in messages
