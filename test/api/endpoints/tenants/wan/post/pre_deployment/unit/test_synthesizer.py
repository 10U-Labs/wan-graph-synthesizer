"""Unit tests for the synthesizer Lambda handler.

The heavy synthesis pipeline is stubbed (it is exercised by the synthesizer engine tests);
these tests cover the handler's own orchestration and S3 I/O: it reads the tenant from
the invoke event, moves the status to ``synthesizing``, and publishes ``success`` or
``fail``.
"""

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
    """Load the synthesizer handler with the store bucket configured."""
    monkeypatch.setenv("STORE_BUCKET", "test-bucket")
    return load_module_from_path("synthesizer_handler", _PATH)


def _stub_pipeline(module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the heavy synthesis pipeline with light canned stand-ins."""
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
    monkeypatch.setattr(module, "load_substrate", lambda *_a: (graph, {}))
    monkeypatch.setattr(module, "load_sites", lambda _p: [])
    monkeypatch.setattr(module, "load_regions", lambda _p: [])
    monkeypatch.setattr(module, "load_off_net", lambda _p: [])
    monkeypatch.setattr(module, "app_config_from_parts", lambda _p: config)
    monkeypatch.setattr(module, "dual_home", lambda *_a: (graph, {}))
    monkeypatch.setattr(
        module, "apply_role_overrides", lambda *_a: (graph, {}, RoleOverrides())
    )
    monkeypatch.setattr(module, "synthesize_two_tier", lambda *_a: object())
    # The synthesis carries its backbone because the handler measures the coverage it
    # delivered before publishing, and its floor because the handler publishes that beside
    # the coverage; the rest of it is the stubbed payload's business. The validation report
    # carries the two diverse-path findings for the same reason: the handler republishes
    # them in the status without recomputing either.
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
    """Every object the synthesizer reads (content unused; pipeline stubbed)."""
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
    """Stub the pipeline (optionally failing the synthesize), run it, return the store."""
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


def test_marks_the_status_success_on_a_good_build(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A build that published its WAN records a 'success' status."""
    objects = _run(synthesizer, monkeypatch)
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "success"


def test_the_success_status_says_whether_the_coverage_target_was_met(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A published build records what it did about the target, not just that it finished.

    The lone site sits inside the target here, so this build met it -- and a build that
    stopped short would be published under the same word without this.
    """
    objects = _run(synthesizer, monkeypatch)
    status = json.loads(objects["tenants/f-35/wan-status.json"])
    assert status["coverage"]["met"] is True


def test_the_success_status_carries_the_target_the_synthesis_was_measured_against(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tenant's own coverage target travels with the measurement of its synthesis."""
    objects = _run(synthesizer, monkeypatch)
    status = json.loads(objects["tenants/f-35/wan-status.json"])
    assert status["coverage"]["target_miles"] == 600


def test_the_success_status_carries_the_backup_path_multiple_the_build_ran_under(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bound the links were drawn under travels with the network they were drawn for.

    An operator can move the bound, and until the tenant is rebuilt what is published is a
    network built to the old one. Without this a reader has no way to tell that from a
    network that ignores the bound, since nothing in the collections says which it is.
    """
    objects = _run(synthesizer, monkeypatch)
    status = json.loads(objects["tenants/f-35/wan-status.json"])
    assert status["max_backup_path_multiple"] == 3.0


def test_the_success_status_carries_the_floor_the_synthesis_is_judged_against(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fewest miles the same requirements could have been met with is published too.

    A reader outside the build can add up the fiber a published network ordered and cannot
    work out what the least it could have run was, because that answer needs the whole
    carrier map and the tenant's requirements together. So the build publishes it, and the
    network is held to twice it (GitHub issue #60).
    """
    objects = _run(synthesizer, monkeypatch)
    status = json.loads(objects["tenants/f-35/wan-status.json"])
    assert status["backbone_lower_bound_miles"] == 1250.0


def test_the_success_status_carries_what_each_site_was_asked_for(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The count that set each site's target is published beside the network it shaped.

    Nothing in the collections says how many independently failing links a site was asked
    to hold, so a reader outside the build cannot tell a thin site the fiber explains from
    one the build got wrong (GitHub issue #45).
    """
    objects = _run(synthesizer, monkeypatch)
    status = json.loads(objects["tenants/f-35/wan-status.json"])
    assert status["diverse_paths"]["ceilings"] == [
        {"id": "P", "name": "P", "ceiling": 1, "target": 1}
    ]


def test_the_success_status_carries_the_sites_short_of_their_target(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shortfall the build found is published rather than left in the Lambda's log.

    This is the half a reader acts on. A site short of its target is either a link somebody
    can still wire or a target the tool should never have set, and neither question can be
    asked of a network that never says the site was short.
    """
    objects = _run(synthesizer, monkeypatch)
    status = json.loads(objects["tenants/f-35/wan-status.json"])
    assert status["diverse_paths"]["short"] == []


def test_the_status_says_synthesizing_while_the_build_runs(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The word a caller polling the GET sees for as long as the work is being done.

    It is the only sign the synthesizer picked the work up at all, and a build that never
    wrote it would look to a caller exactly like one the dispatcher never started. It is
    read from inside the build here because the store keeps only the last status written,
    so every other test in this file reads a build that has already finished.
    """
    _stub_pipeline(synthesizer, monkeypatch)
    objects = _inputs(synthesizer)
    polled: list[dict[str, Any]] = []

    def _read_the_status_mid_build(*_args: Any) -> Any:
        """Stand in for the long step, reading what a caller would see while it runs."""
        polled.append(json.loads(objects["tenants/f-35/wan-status.json"]))
        return object()

    monkeypatch.setattr(synthesizer, "synthesize_two_tier", _read_the_status_mid_build)
    with patch("boto3.client", return_value=fake_s3(objects)):
        synthesizer.lambda_handler({"tenant": "f-35"}, None)
    assert polled[0]["status"] == "synthesizing"


def test_records_fail_when_no_valid_wan(
    synthesizer: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the synthesizer reports infeasibility, the status is recorded as ``fail``."""
    objects = _run(synthesizer, monkeypatch, fail=True)
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "fail"


def _run_split_backbone(module: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Run a build whose synthesis falls into two groups, with the real finalize gating it.

    Everything the synthesis is made of is stubbed as it is everywhere else in this file; what
    is not stubbed is ``finalize``, because the gate under test is the one it holds. The
    synthesis it is handed is four backbone sites whose fiber joins a to b through the
    transit city t and c to d, with nothing between the two pairs.
    """
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
    """A synthesis in two groups is recorded as ``fail``, which is how the gate is seen outside.

    The refusal happens inside the build, so a caller polling the GET learns of it only
    through this status; without it the tenant would sit at ``synthesizing`` forever.
    """
    objects = _run_split_backbone(synthesizer, monkeypatch)
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "fail"


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
