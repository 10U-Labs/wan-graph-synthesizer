"""WAN create endpoint: run a tenant's synthesize on Fargate and report its status.

    POST /wan-graph-synthesizer/tenants/{tenant}/wan -> 202; start the create
    GET  /wan-graph-synthesizer/tenants/{tenant}/wan -> the WAN's status (422 if failed)

The synthesize math is slow, so a POST launches a Fargate Spot task (the synthesizer
container) and returns immediately; the task writes the finished WAN and a status marker
to S3. A GET reads that marker -- 422 when no valid WAN was possible, 404 before the
first create.

The task runs on Fargate Spot for cost -- always Spot, never on-demand. Spot fails two
ways, each retried on Spot up to the same cap (tracked by an Attempt tag), then recorded
failed. (1) A reclaim kills a running task mid-build: the same Lambda receives ECS "task
stopped" events from EventBridge and relaunches. (2) A capacity shortfall means run_task
places nothing (no task, so no stopped event): the Lambda reads run_task's failures and
schedules a one-shot EventBridge Scheduler retry that re-invokes it with a "wan.retry"
event. Self-contained (stdlib + boto3); single-file Lambda.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
# How many times a Spot build is relaunched before giving up -- shared by both Spot
# failure modes (an interruption of a running task, and a placement shortfall that never
# starts one). The build is deterministic and self-contained, so a fresh attempt simply
# restarts it.
MAX_ATTEMPTS = 5
# How long to wait before retrying a Spot placement shortfall, giving capacity time to free.
RETRY_DELAY_MINUTES = 2


def _s3() -> Any:
    """Return the cached S3 client, creating it on first use."""
    if "s3" not in _CLIENTS:
        _CLIENTS["s3"] = boto3.client("s3", region_name="us-east-2")
    return _CLIENTS["s3"]


def _ecs() -> Any:
    """Return the cached ECS client, creating it on first use."""
    if "ecs" not in _CLIENTS:
        _CLIENTS["ecs"] = boto3.client("ecs", region_name="us-east-2")
    return _CLIENTS["ecs"]


def _scheduler() -> Any:
    """Return the cached EventBridge Scheduler client, creating it on first use."""
    if "scheduler" not in _CLIENTS:
        _CLIENTS["scheduler"] = boto3.client("scheduler", region_name="us-east-2")
    return _CLIENTS["scheduler"]


def clear_clients() -> None:
    """Drop cached clients (tests reset between cases)."""
    _CLIENTS.clear()


def _response(status: int, body: Any) -> dict[str, Any]:
    """Build an API Gateway proxy response with open CORS."""
    return {"statusCode": status, "headers": dict(_HEADERS), "body": json.dumps(body)}


def _status_key(tenant: str) -> str:
    """The S3 key holding a tenant's WAN status marker."""
    return f"tenants/{tenant}/wan-status.json"


def _run_synthesizer_task(tenant: str, attempt: int) -> list[dict[str, Any]]:
    """Launch the Fargate Spot synthesizer for a tenant; return its placement failures.

    The Tenant and Attempt tags let the task-stopped handler relaunch this exact build (and
    count attempts) when Spot reclaims the task mid-run. ``run_task`` reports a Spot capacity
    shortfall in its ``failures`` list rather than raising, so this returns it (empty on
    success) for the caller to act on instead of letting the build hang at ``creating``.
    """
    response = _ecs().run_task(
        cluster=os.environ["CLUSTER_ARN"],
        taskDefinition=os.environ["TASK_DEFINITION_ARN"],
        capacityProviderStrategy=[{"capacityProvider": "FARGATE_SPOT", "weight": 1}],
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": [os.environ["SUBNET_ID"]],
                "securityGroups": [os.environ["SECURITY_GROUP_ID"]],
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={
            "containerOverrides": [
                {"name": "synthesizer", "environment": [
                    {"name": "TENANT", "value": tenant}]}
            ]
        },
        tags=[
            {"key": "Tenant", "value": tenant},
            {"key": "Attempt", "value": str(attempt)},
        ],
    )
    failures: list[dict[str, Any]] = response.get("failures", [])
    return failures


def _write_status(tenant: str, payload: dict[str, Any]) -> None:
    """Write a tenant's WAN status marker to the store."""
    _s3().put_object(
        Bucket=os.environ["STORE_BUCKET"],
        Key=_status_key(tenant),
        Body=json.dumps(payload).encode(),
    )


def _schedule_retry(tenant: str, attempt: int, context: Any) -> None:
    """Schedule a one-shot Spot relaunch ``RETRY_DELAY_MINUTES`` from now.

    A placement shortfall never starts a task, so the task-stopped retry can't see it.
    Instead a one-time EventBridge Scheduler schedule re-invokes this Lambda with a
    ``wan.retry`` event to try Spot again (never on-demand), and deletes itself after firing.
    """
    when = datetime.now(timezone.utc) + timedelta(minutes=RETRY_DELAY_MINUTES)
    _scheduler().create_schedule(
        Name=f"wan-retry-{tenant}-{attempt}",
        ScheduleExpression=f"at({when.strftime('%Y-%m-%dT%H:%M:%S')})",
        FlexibleTimeWindow={"Mode": "OFF"},
        ActionAfterCompletion="DELETE",
        Target={
            "Arn": context.invoked_function_arn,
            "RoleArn": os.environ["SCHEDULER_ROLE_ARN"],
            "Input": json.dumps(
                {"source": "wan.retry", "tenant": tenant, "attempt": attempt}
            ),
        },
    )


def _launch_or_fail(tenant: str, attempt: int, context: Any) -> None:
    """Launch the Spot build; retry on Spot if it can't place, or fail past the cap.

    Spot is the only capacity provider (never on-demand): a capacity shortfall is retried on
    Spot via a delayed schedule until ``MAX_ATTEMPTS``, then recorded ``failed`` so the tenant
    reaches a terminal answer instead of an endless ``creating``.
    """
    failures = _run_synthesizer_task(tenant, attempt)
    if not failures:
        return
    if attempt < MAX_ATTEMPTS:
        _schedule_retry(tenant, attempt + 1, context)
        return
    reason = "; ".join(failure.get("reason", "unknown") for failure in failures)
    _write_status(
        tenant, {"status": "failed", "reason": f"could not place synthesizer on Spot: {reason}"}
    )


def _start_create(tenant: str, context: Any) -> None:
    """Mark the WAN as creating and launch the first synthesizer attempt."""
    _write_status(tenant, {"status": "creating", "tenant": tenant})
    _launch_or_fail(tenant, 1, context)


def _read_status(tenant: str) -> dict[str, Any]:
    """Serve a tenant's WAN status: 422 when failed, 404 before any create."""
    client = _s3()
    try:
        body = client.get_object(
            Bucket=os.environ["STORE_BUCKET"], Key=_status_key(tenant)
        )["Body"].read()
    except client.exceptions.NoSuchKey:
        return _response(404, {"error": f"no wan: {tenant}"})
    status = json.loads(body)
    code = 422 if status.get("status") == "failed" else 200
    return _response(code, status)


def _is_spot_interruption(stop_code: str, stopped_reason: str) -> bool:
    """True if an ECS task stop looks like a Spot reclaim (vs a normal exit)."""
    text = f"{stop_code} {stopped_reason}".lower()
    return "spot" in text or "capacity" in text


def _task_tags(task_arn: str, cluster_arn: str) -> dict[str, str]:
    """The tag key/value pairs of a (possibly stopped) ECS task."""
    response = _ecs().describe_tasks(
        cluster=cluster_arn, tasks=[task_arn], include=["TAGS"]
    )
    tasks = response.get("tasks", [])
    if not tasks:
        return {}
    return {tag["key"]: tag["value"] for tag in tasks[0].get("tags", [])}


def _handle_task_stopped(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Relaunch a Spot-interrupted synthesizer build, or fail it past the cap."""
    detail = event.get("detail", {})
    if detail.get("lastStatus") != "STOPPED":
        return {"handled": False, "reason": "not stopped"}
    if not _is_spot_interruption(detail.get("stopCode", ""), detail.get("stoppedReason", "")):
        return {"handled": False, "reason": "not a spot interruption"}
    tags = _task_tags(detail.get("taskArn", ""), detail.get("clusterArn", ""))
    tenant = tags.get("Tenant")
    if not tenant:
        return {"handled": False, "reason": "not a synthesizer task"}
    attempt = int(tags.get("Attempt", "1"))
    if attempt >= MAX_ATTEMPTS:
        logger.warning("Giving up on %s after %d Spot interruptions", tenant, attempt)
        _write_status(
            tenant, {"status": "failed", "reason": f"interrupted {attempt} times by Spot reclaims"}
        )
        return {"handled": True, "retried": False, "tenant": tenant}
    logger.info("Relaunching %s after Spot interruption (attempt %d)", tenant, attempt + 1)
    _launch_or_fail(tenant, attempt + 1, context)
    return {"handled": True, "retried": True, "tenant": tenant}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Dispatch: task-stopped events, delayed Spot retries, or API Gateway create/status."""
    if event.get("source") == "aws.ecs":
        return _handle_task_stopped(event, context)
    if event.get("source") == "wan.retry":
        _launch_or_fail(event["tenant"], int(event["attempt"]), context)
        return {"retried": True, "tenant": event["tenant"]}
    tenant = (event.get("pathParameters") or {}).get("tenant")
    if not tenant:
        return _response(404, {"error": "tenant required"})
    if event.get("httpMethod") == "POST":
        _start_create(tenant, context)
        return _response(202, {"status": "creating", "tenant": tenant})
    return _read_status(tenant)
