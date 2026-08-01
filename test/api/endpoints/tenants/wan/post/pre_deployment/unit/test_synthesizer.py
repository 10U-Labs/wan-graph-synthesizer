"""Unit tests for the synthesizer Lambda handler.

The heavy design pipeline is stubbed (it is exercised by the synthesizer engine tests);
these tests cover the handler's own orchestration and S3 I/O: it reads the tenant from
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
from synthesizer.model import DesignParams, OperatorLinks, RoleOverrides

_PATH = REPO_ROOT / "src/api/endpoints/tenants/wan/post/lambdas/synthesizer/handler.py"


@pytest.fixture(name="synthesizer")
def synthesizer_fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the synthesizer handler with the store bucket configured."""
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    return load_module_from_path("synthesizer_handler", _PATH)


def _stub_pipeline(
    module: Any, monkeypatch: pytest.MonkeyPatch, restrict: bool = True
) -> None:
    """Replace the heavy design pipeline with light canned stand-ins.

    ``restrict`` sets ``config.restrict_backbone_to_datacenters`` so both handler
    branches -- gating the backbone to data-center cities vs the open free-for-all --
    are exercised across the suite.
    """
    pop = Vertex(id="P", name="P", kind="PoP", coords=(0.0, 0.0))
    site = Vertex(id="S", name="S", kind="Tenant site", coords=(1.0, 1.0))
    graph = [pop, site]
    config = SimpleNamespace(
        params=DesignParams(),
        restrict_backbone_to_datacenters=restrict,
        links=OperatorLinks(),
    )
    payload = {
        "vertices": [{"id": "P", "tier_role": "backbone"}],
        "access_edges": [],
        "physical_edges": [],
        "path_uses": [{"purpose": "backbone_mesh", "source_name": "P", "target_name": "Q"}],
    }
    monkeypatch.setattr(module, "load_substrate", lambda *_a: (graph, {}))
    monkeypatch.setattr(module, "load_sites", lambda _p: [])
    monkeypatch.setattr(module, "load_regions", lambda _p: [])
    monkeypatch.setattr(module, "load_off_net", lambda _p: [])
    monkeypatch.setattr(module, "app_config_from_parts", lambda _p: config)
    monkeypatch.setattr(module, "dual_home", lambda *_a: (graph, {}))
    monkeypatch.setattr(
        module, "apply_role_overrides", lambda *_a: (graph, {}, RoleOverrides())
    )
    monkeypatch.setattr(module, "synthesize_two_tier_design", lambda *_a: object())
    # The design carries its backbone because the handler measures the coverage it
    # delivered before publishing; the rest of it is the stubbed payload's business.
    design = SimpleNamespace(backbone_ids=("P",))
    monkeypatch.setattr(module, "finalize", lambda *_a: (graph, {}, design, {}))
    monkeypatch.setattr(module, "design_payload", lambda *_a: payload)


def _inputs(module: Any) -> dict[str, bytes]:
    """Every object the synthesizer reads (content unused; pipeline stubbed)."""
    keys = [
        "carriers/merge/vertices.json",
        "carriers/merge/edges.json",
        "data-centers/merge/vertices.json",
        "tenants/f-35/locations.json",
        "tenants/f-35/provider-regions.json",
        "tenants/f-35/off-net.json",
    ]
    keys += [f"tenants/f-35/{resource}.json" for resource in module.CONFIG_RESOURCES]
    return {key: b"[]" for key in keys}


def _run(module: Any, monkeypatch: pytest.MonkeyPatch, fail: bool = False) -> dict[str, bytes]:
    """Stub the pipeline (optionally failing the synthesize), run it, return the store."""
    _stub_pipeline(module, monkeypatch)
    if fail:

        def _raise(*_args: Any) -> Any:
            raise ValueError("No feasible design")

        monkeypatch.setattr(module, "synthesize_two_tier_design", _raise)
    objects = _inputs(module)
    with patch("boto3.client", return_value=fake_s3(objects)):
        module.lambda_handler({"tenant": "f-35"}, None)
    return objects


def test_reads_the_degree_exempt_backbone_nodes(synthesizer: Any) -> None:
    """The build reads the exemption list among the tenant's config resources."""
    assert "degree-exempt-backbone-nodes" in synthesizer.CONFIG_RESOURCES


def test_publishes_the_wan_on_success(synthesizer: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful build writes the tenant's WAN JSON to the store."""
    objects = _run(synthesizer, monkeypatch)
    assert "tenants/f-35/wan.json" in objects


def test_publishes_the_backbone_links_collection(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The published WAN carries the backbone-to-backbone links as their own collection."""
    objects = _run(synthesizer, monkeypatch)
    wan = json.loads(objects["tenants/f-35/wan.json"])
    assert wan["backbone-links"] == [
        {"purpose": "backbone_mesh", "source_name": "P", "target_name": "Q"}
    ]


def test_marks_status_ready_on_success(synthesizer: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful build records a 'ready' status."""
    objects = _run(synthesizer, monkeypatch)
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "ready"


def test_the_ready_status_says_whether_the_coverage_target_was_met(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A published build records what it did about the target, not just that it finished.

    The lone site sits inside the target here, so this build met it -- and a build that
    stopped short would be published under the same word without this.
    """
    objects = _run(synthesizer, monkeypatch)
    status = json.loads(objects["tenants/f-35/wan-status.json"])
    assert status["coverage"]["met"] is True


def test_the_ready_status_carries_the_target_the_design_was_measured_against(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tenant's own coverage target travels with the measurement of its design."""
    objects = _run(synthesizer, monkeypatch)
    status = json.loads(objects["tenants/f-35/wan-status.json"])
    assert status["coverage"]["target_miles"] == 600


def test_records_failed_when_no_valid_wan(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the synthesizer reports infeasibility, the status is recorded as failed."""
    objects = _run(synthesizer, monkeypatch, fail=True)
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "failed"


def test_open_gate_build_maps_to_no_datacenter_restriction(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With restrict off, the handler opens the gate (datacenter_cities=None) and still builds."""
    _stub_pipeline(synthesizer, monkeypatch, restrict=False)
    objects = _inputs(synthesizer)
    with patch("boto3.client", return_value=fake_s3(objects)):
        synthesizer.lambda_handler({"tenant": "f-35"}, None)
    assert "tenants/f-35/wan.json" in objects


def test_reads_the_tenant_from_the_event(synthesizer: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The synthesizer builds the tenant named in the invoke event."""
    _stub_pipeline(synthesizer, monkeypatch)
    objects = _inputs(synthesizer)
    with patch("boto3.client", return_value=fake_s3(objects)):
        synthesizer.lambda_handler({"tenant": "f-35"}, None)
    assert "tenants/f-35/wan.json" in objects


def test_logs_progress_at_info(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A run emits INFO progress so a long build is observable, not silent."""
    with caplog.at_level(logging.INFO):
        _run(synthesizer, monkeypatch)
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "f-35" in messages and "Publishing" in messages
