"""Unit tests for the tenants/wan endpoint Lambda handler.

The WAN resource launches the synthesizer as a Fargate Spot task and recovers Spot
interruptions by relaunching at the next attempt. All of this is endpoint-specific.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from test_handler_contracts import load_handler
from test_s3_store_mock import fake_ecs, fake_s3


def _wan(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Load the wan handler with the create task's environment configured."""
    return load_handler(
        "tenants/wan",
        monkeypatch,
        CLUSTER_ARN="arn:cluster",
        TASK_DEFINITION_ARN="arn:task",
        SUBNET_ID="subnet-1",
        SECURITY_GROUP_ID="sg-1",
    )


def _wan_clients(
    objects: dict[str, bytes],
    started: list[dict[str, Any]],
    task_tags: dict[str, str] | None = None,
) -> Any:
    """A boto3.client side effect handing back the S3 and ECS fakes by service."""
    fakes = {"s3": fake_s3(objects), "ecs": fake_ecs(started, task_tags)}
    return lambda service, **_kwargs: fakes[service]


def _stopped_event(
    stop_code: str = "SpotInterruption",
    reason: str = "Your Spot Task was interrupted.",
    last_status: str = "STOPPED",
) -> dict[str, Any]:
    """An EventBridge ECS Task State Change event for the synthesizer cluster."""
    return {
        "source": "aws.ecs",
        "detail-type": "ECS Task State Change",
        "detail": {
            "lastStatus": last_status,
            "stopCode": stop_code,
            "stoppedReason": reason,
            "taskArn": "arn:aws:ecs:task/abc",
            "clusterArn": "arn:cluster",
        },
    }


def test_wan_post_returns_202(monkeypatch: pytest.MonkeyPatch) -> None:
    """Starting a create acknowledges with 202."""
    module = _wan(monkeypatch)
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients({}, [])):
        response = module.lambda_handler(event, None)
    assert response["statusCode"] == 202


def test_wan_post_launches_one_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """A create launches exactly one synthesizer task."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients({}, started)):
        module.lambda_handler(event, None)
    assert len(started) == 1


def test_wan_post_launches_on_spot(monkeypatch: pytest.MonkeyPatch) -> None:
    """The create runs on Fargate Spot for cost (interruptions are recovered)."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients({}, started)):
        module.lambda_handler(event, None)
    assert started[0]["capacityProviderStrategy"][0]["capacityProvider"] == "FARGATE_SPOT"


def test_wan_post_tags_task_for_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first attempt is tagged Tenant + Attempt 1 so a reclaim can be relaunched."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients({}, started)):
        module.lambda_handler(event, None)
    assert started[0]["tags"] == [
        {"key": "Tenant", "value": "f-35"},
        {"key": "Attempt", "value": "1"},
    ]


def test_spot_interruption_relaunches_with_next_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Spot-interrupted build relaunches for the same tenant at the next attempt."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    tags = {"Tenant": "f-35", "Attempt": "1"}
    with patch("boto3.client", side_effect=_wan_clients({}, started, tags)):
        module.lambda_handler(_stopped_event(), None)
    assert started[0]["tags"] == [
        {"key": "Tenant", "value": "f-35"},
        {"key": "Attempt", "value": "2"},
    ]


def test_spot_interruption_past_cap_marks_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Past the attempt cap the build is recorded failed instead of relaunched again."""
    module = _wan(monkeypatch)
    objects: dict[str, bytes] = {}
    started: list[dict[str, Any]] = []
    tags = {"Tenant": "f-35", "Attempt": str(module.MAX_ATTEMPTS)}
    with patch("boto3.client", side_effect=_wan_clients(objects, started, tags)):
        module.lambda_handler(_stopped_event(), None)
    assert json.loads(objects["tenants/f-35/wan-status.json"])["status"] == "failed"


def test_non_spot_stop_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A normal (non-Spot) task stop is not relaunched."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    event = _stopped_event(stop_code="EssentialContainerExited", reason="container exited")
    with patch("boto3.client", side_effect=_wan_clients({}, started, {"Tenant": "f-35"})):
        module.lambda_handler(event, None)
    assert not started


def test_running_task_event_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-STOPPED task-state event is ignored."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    with patch("boto3.client", side_effect=_wan_clients({}, started, {"Tenant": "f-35"})):
        result = module.lambda_handler(_stopped_event(last_status="RUNNING"), None)
    assert result["handled"] is False


def test_stop_of_unknown_task_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Spot stop of a task with no Tenant tag (or already gone) is not relaunched."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    with patch("boto3.client", side_effect=_wan_clients({}, started, None)):
        module.lambda_handler(_stopped_event(), None)
    assert not started


def test_stop_without_tenant_tag_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Spot stop of a tagged-but-not-ours task is not relaunched."""
    module = _wan(monkeypatch)
    started: list[dict[str, Any]] = []
    with patch("boto3.client", side_effect=_wan_clients({}, started, {"Other": "x"})):
        module.lambda_handler(_stopped_event(), None)
    assert not started


def test_wan_post_marks_status_creating(monkeypatch: pytest.MonkeyPatch) -> None:
    """A create records a 'creating' status marker in the store."""
    module = _wan(monkeypatch)
    objects: dict[str, bytes] = {}
    event = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients(objects, [])):
        module.lambda_handler(event, None)
    assert "tenants/f-35/wan-status.json" in objects


def test_wan_get_404_before_any_create(monkeypatch: pytest.MonkeyPatch) -> None:
    """A WAN status read before any create is a 404."""
    module = _wan(monkeypatch)
    with patch("boto3.client", side_effect=_wan_clients({}, [])):
        response = module.lambda_handler({"pathParameters": {"tenant": "f-35"}}, None)
    assert response["statusCode"] == 404


def test_wan_get_200_while_creating(monkeypatch: pytest.MonkeyPatch) -> None:
    """A WAN still being created reports 200 with its status."""
    module = _wan(monkeypatch)
    objects = {"tenants/f-35/wan-status.json": json.dumps({"status": "creating"}).encode()}
    with patch("boto3.client", side_effect=_wan_clients(objects, [])):
        response = module.lambda_handler({"pathParameters": {"tenant": "f-35"}}, None)
    assert response["statusCode"] == 200


def test_wan_get_422_when_no_valid_wan(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed create reports 422 (no valid WAN was possible)."""
    module = _wan(monkeypatch)
    objects = {"tenants/f-35/wan-status.json": json.dumps({"status": "failed"}).encode()}
    with patch("boto3.client", side_effect=_wan_clients(objects, [])):
        response = module.lambda_handler({"pathParameters": {"tenant": "f-35"}}, None)
    assert response["statusCode"] == 422


def test_wan_404_when_no_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """A request without a tenant path parameter is a 404."""
    module = _wan(monkeypatch)
    with patch("boto3.client", side_effect=_wan_clients({}, [])):
        response = module.lambda_handler({}, None)
    assert response["statusCode"] == 404


def test_wan_caches_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two creates build the S3 and ECS clients once each, then reuse them."""
    module = _wan(monkeypatch)
    post = {"httpMethod": "POST", "pathParameters": {"tenant": "f-35"}}
    with patch("boto3.client", side_effect=_wan_clients({}, [])) as mock_client:
        module.lambda_handler(post, None)
        module.lambda_handler(post, None)
    assert mock_client.call_count == 2
