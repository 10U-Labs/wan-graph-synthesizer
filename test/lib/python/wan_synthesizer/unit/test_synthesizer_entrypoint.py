"""Unit tests for the Fargate synthesizer entrypoint.

The heavy design pipeline is stubbed (it is exercised by the wan_synthesizer tests);
these tests cover the entrypoint's own orchestration and S3 I/O.
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
from wan_graph.model import Vertex

_PATH = REPO_ROOT / "src/api/endpoints/customers/wan/synthesizer/entrypoint.py"


@pytest.fixture(name="entrypoint")
def entrypoint_fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the synthesizer entrypoint with the task environment configured."""
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    monkeypatch.setenv("CUSTOMER", "f-35")
    return load_module_from_path("synthesizer_entrypoint", _PATH)


def _stub_pipeline(module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the heavy design pipeline with light canned stand-ins."""
    pop = Vertex(id="P", name="P", tenant="Lumen", kind="PoP", coords=(0.0, 0.0))
    site = Vertex(
        id="S", name="S", tenant="F-35", kind="Military installation", coords=(1.0, 1.0)
    )
    graph = [pop, site]
    config = SimpleNamespace(
        params=None,
        forced_connections=(),
        excluded_connections=(),
    )
    payload = {
        "vertices": [{"id": "P", "tier_role": "core"}],
        "access_edges": [],
        "physical_edges": [],
    }
    monkeypatch.setattr(module, "load_input_graph", lambda _p: (graph, {}))
    monkeypatch.setattr(module, "app_config_from_parts", lambda _p: config)
    monkeypatch.setattr(module, "dual_home", lambda *_a: (graph, {}))
    monkeypatch.setattr(module, "apply_role_overrides", lambda *_a: (graph, {}, object()))
    monkeypatch.setattr(module, "synthesize_three_tier_design", lambda *_a: object())
    monkeypatch.setattr(module, "finalize", lambda *_a: (graph, {}, object(), {}))
    monkeypatch.setattr(module, "design_payload", lambda *_a: payload)


def _inputs(module: Any) -> dict[str, bytes]:
    """Every object the entrypoint reads (content unused; pipeline stubbed)."""
    keys = [
        "merge/substrate.json",
        "customers/f-35/locations.json",
        "customers/f-35/csp-regions.json",
        "customers/f-35/off-net.json",
    ]
    keys += [f"customers/f-35/{resource}.json" for resource in module.CONFIG_RESOURCES]
    return {key: b"{}" for key in keys}


def _run_main(module: Any, monkeypatch: pytest.MonkeyPatch, fail: bool = False) -> dict[str, bytes]:
    """Stub the pipeline (optionally failing the synthesize), run main, return the store."""
    _stub_pipeline(module, monkeypatch)
    if fail:

        def _raise(*_args: Any) -> Any:
            raise ValueError("No feasible design")

        monkeypatch.setattr(module, "synthesize_three_tier_design", _raise)
    objects = _inputs(module)
    with patch("boto3.client", return_value=fake_s3(objects)):
        module.main()
    return objects


def test_publishes_the_wan_on_success(entrypoint: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful build writes the customer's WAN JSON to the store."""
    objects = _run_main(entrypoint, monkeypatch)
    assert "customers/f-35/wan.json" in objects


def test_marks_status_ready_on_success(entrypoint: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful build records a 'ready' status."""
    objects = _run_main(entrypoint, monkeypatch)
    assert json.loads(objects["customers/f-35/wan-status.json"])["status"] == "ready"


def test_records_failed_when_no_valid_wan(entrypoint: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the synthesizer reports infeasibility, the status is recorded as failed."""
    objects = _run_main(entrypoint, monkeypatch, fail=True)
    assert json.loads(objects["customers/f-35/wan-status.json"])["status"] == "failed"


def test_main_logs_progress_at_info(
    entrypoint: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A run emits INFO progress so a long build is observable, not silent."""
    with caplog.at_level(logging.INFO):
        _run_main(entrypoint, monkeypatch)
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "f-35" in messages and "Publishing" in messages
