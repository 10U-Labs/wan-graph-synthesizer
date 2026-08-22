from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import fixtures
import pytest

from repo_utils import REPO_ROOT
from test_module_utils import load_module_from_path
from test_s3_store_mock import fake_s3
from synthesizer.input_graph import Site
from synthesizer.model import SynthesisParams, OperatorLinks, RoleOverrides
from synthesizer.stages import finalize

_PATH = REPO_ROOT / "src/api/endpoints/tenants/wan/post/lambdas/synthesizer/handler.py"


@pytest.fixture(name="synthesizer")
def synthesizer_fixture(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    return load_module_from_path("synthesizer_handler", _PATH)


def _stub_pipeline(module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    pop = Site(id="P", name="P", kind="PoP", coords=(0.0, 0.0))
    site = Site(id="S", name="S", kind="Tenant site", coords=(1.0, 1.0))
    graph = [pop, site]
    config = SimpleNamespace(
        params=SynthesisParams(),
        links=OperatorLinks(),
    )
    payload = {
        "sites": [{"id": "P", "tier_role": "backbone"}],
        "access_paths": [],
        "fiber_segments": [],
        "path_uses": [{"purpose": "backbone_mesh", "source_name": "P", "target_name": "Q"}],
    }
    monkeypatch.setattr(module, "load_merged_carriers", lambda *_a: (graph, {}))
    monkeypatch.setattr(module, "load_sites", lambda _p: [])
    monkeypatch.setattr(module, "load_regions", lambda _p: [])
    monkeypatch.setattr(module, "load_off_net", lambda _p: [])
    monkeypatch.setattr(module, "app_config_from_parts", lambda _p: config)
    monkeypatch.setattr(module, "dual_home", lambda *_a: (graph, {}))
    monkeypatch.setattr(
        module, "apply_role_overrides", lambda *_a: (graph, {}, RoleOverrides())
    )
    monkeypatch.setattr(module, "synthesize_two_tier", lambda *_a: object())
    synthesis = SimpleNamespace(
        backbone_ids=("P",),
        metrics=SimpleNamespace(backbone_lower_bound_miles=1250.0),
    )
    validation = {
        "backbone_diverse_paths_ceilings": [
            {"id": "P", "name": "P", "ceiling": 1, "target": 1}
        ],
        "backbone_mesh_independence_deficient": [],
    }
    monkeypatch.setattr(module, "finalize", lambda *_a: (graph, {}, synthesis, validation))
    monkeypatch.setattr(module, "synthesis_payload", lambda *_a: payload)


def _inputs(module: Any) -> dict[str, bytes]:
    keys = [
        "carriers/merge/pops.json",
        "carriers/merge/fiber-segments.json",
        "tenants/f-35/locations.json",
        "tenants/f-35/provider-regions.json",
        "tenants/f-35/off-net.json",
    ]
    keys += [f"tenants/f-35/{resource}.json" for resource in module.CONFIG_RESOURCES]
    return {key: b"[]" for key in keys}


def _run(module: Any, monkeypatch: pytest.MonkeyPatch, fail: bool = False) -> dict[str, bytes]:
    _stub_pipeline(module, monkeypatch)
    if fail:

        def _raise(*_args: Any) -> Any:
            raise ValueError("No feasible synthesis")

        monkeypatch.setattr(module, "synthesize_two_tier", _raise)
    objects = _inputs(module)
    with patch("boto3.client", return_value=fake_s3(objects)):
        module.lambda_handler({"tenant": "f-35"}, None)
    return objects


def test_reads_the_degree_exempt_backbone_nodes(synthesizer: Any) -> None:
    assert "degree-exempt-backbone-nodes" in synthesizer.CONFIG_RESOURCES


def test_publishes_the_wan_on_success(synthesizer: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    objects = _run(synthesizer, monkeypatch)
    assert "tenants/f-35/wan.json" in objects


def test_publishes_the_backbone_links_collection(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects = _run(synthesizer, monkeypatch)
    wan = json.loads(objects["tenants/f-35/wan.json"])
    assert wan["backbone-links"] == [
        {"purpose": "backbone_mesh", "source_name": "P", "target_name": "Q"}
    ]


def test_marks_the_status_success_on_a_good_build(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects = _run(synthesizer, monkeypatch)
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "success"


def test_the_success_status_says_whether_the_coverage_target_was_met(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects = _run(synthesizer, monkeypatch)
    status = json.loads(objects["tenants/f-35/wan-status.json"])
    assert status["coverage"]["met"] is True


def test_the_success_status_carries_the_target_the_synthesis_was_measured_against(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects = _run(synthesizer, monkeypatch)
    status = json.loads(objects["tenants/f-35/wan-status.json"])
    assert status["coverage"]["target_miles"] == 600


def test_the_success_status_carries_no_backup_path_multiple(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects = _run(synthesizer, monkeypatch)
    status = json.loads(objects["tenants/f-35/wan-status.json"])
    assert "max_backup_path_multiple" not in status


def test_the_success_status_carries_the_floor_the_synthesis_is_judged_against(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects = _run(synthesizer, monkeypatch)
    status = json.loads(objects["tenants/f-35/wan-status.json"])
    assert status["backbone_lower_bound_miles"] == 1250.0


def test_the_success_status_carries_what_each_site_was_asked_for(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects = _run(synthesizer, monkeypatch)
    status = json.loads(objects["tenants/f-35/wan-status.json"])
    assert status["diverse_paths"]["ceilings"] == [
        {"id": "P", "name": "P", "ceiling": 1, "target": 1}
    ]


def test_the_success_status_carries_the_sites_short_of_their_target(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects = _run(synthesizer, monkeypatch)
    status = json.loads(objects["tenants/f-35/wan-status.json"])
    assert status["diverse_paths"]["short"] == []


def test_the_status_says_synthesizing_while_the_build_runs(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_pipeline(synthesizer, monkeypatch)
    objects = _inputs(synthesizer)
    polled: list[dict[str, Any]] = []

    def _read_the_status_mid_build(*_args: Any) -> Any:
        polled.append(json.loads(objects["tenants/f-35/wan-status.json"]))
        return object()

    monkeypatch.setattr(synthesizer, "synthesize_two_tier", _read_the_status_mid_build)
    with patch("boto3.client", return_value=fake_s3(objects)):
        synthesizer.lambda_handler({"tenant": "f-35"}, None)
    assert polled[0]["status"] == "synthesizing"


def test_records_fail_when_no_valid_wan(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects = _run(synthesizer, monkeypatch, fail=True)
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "fail"


def _run_split_backbone(module: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    _stub_pipeline(module, monkeypatch)
    graph = list(fixtures.carrier_pops_by_id(fixtures.SPLIT_BACKBONE_CITIES).values())
    fiber = fixtures.fiber_segments_from(fixtures.SPLIT_BACKBONE_SEGMENTS)
    monkeypatch.setattr(module, "dual_home", lambda *_a: (graph, fiber))
    monkeypatch.setattr(
        module, "apply_role_overrides", lambda *_a: (graph, fiber, RoleOverrides())
    )
    monkeypatch.setattr(
        module, "synthesize_two_tier", lambda *_a: fixtures.split_backbone_synthesis()
    )
    monkeypatch.setattr(module, "finalize", finalize)
    objects = _inputs(module)
    with patch("boto3.client", return_value=fake_s3(objects)):
        module.lambda_handler({"tenant": "f-35"}, None)
    return objects


def test_records_fail_when_the_synthesis_falls_into_more_than_one_group(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    objects = _run_split_backbone(synthesizer, monkeypatch)
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "fail"


def test_reads_the_tenant_from_the_event(synthesizer: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_pipeline(synthesizer, monkeypatch)
    objects = _inputs(synthesizer)
    with patch("boto3.client", return_value=fake_s3(objects)):
        synthesizer.lambda_handler({"tenant": "f-35"}, None)
    assert "tenants/f-35/wan.json" in objects


def test_logs_progress_at_info(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        _run(synthesizer, monkeypatch)
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "f-35" in messages and "Publishing" in messages
