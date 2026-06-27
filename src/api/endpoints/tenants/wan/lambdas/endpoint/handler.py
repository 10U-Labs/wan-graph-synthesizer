"""WAN create endpoint: start a tenant's synthesize worker and report its status.

    POST /wan-graph-synthesizer/tenants/{tenant}/wan -> 202; start the create
    GET  /wan-graph-synthesizer/tenants/{tenant}/wan -> the WAN's status (422 if failed)

The synthesize math takes longer than API Gateway's ~29s cap, so a POST async-invokes
the synthesizer worker Lambda and returns immediately; the worker writes the finished WAN
and a status marker to S3. A GET reads that marker -- 422 when no valid WAN was possible,
404 before the first create. Self-contained (stdlib + boto3); single-file Lambda.
"""

import json
import logging
import os
from typing import Any

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}


def _s3() -> Any:
    """Return the cached S3 client, creating it on first use."""
    if "s3" not in _CLIENTS:
        _CLIENTS["s3"] = boto3.client("s3", region_name="us-east-2")
    return _CLIENTS["s3"]


def _lambda() -> Any:
    """Return the cached Lambda client, creating it on first use."""
    if "lambda" not in _CLIENTS:
        _CLIENTS["lambda"] = boto3.client("lambda", region_name="us-east-2")
    return _CLIENTS["lambda"]


def clear_clients() -> None:
    """Drop cached clients (tests reset between cases)."""
    _CLIENTS.clear()


def _response(status: int, body: Any) -> dict[str, Any]:
    """Build an API Gateway proxy response with open CORS."""
    return {"statusCode": status, "headers": dict(_HEADERS), "body": json.dumps(body)}


def _status_key(tenant: str) -> str:
    """The S3 key holding a tenant's WAN status marker."""
    return f"tenants/{tenant}/wan-status.json"


def _write_status(tenant: str, payload: dict[str, Any]) -> None:
    """Write a tenant's WAN status marker to the store."""
    _s3().put_object(
        Bucket=os.environ["STORE_BUCKET"],
        Key=_status_key(tenant),
        Body=json.dumps(payload).encode(),
    )


def _start_create(tenant: str) -> None:
    """Mark the WAN as creating and async-invoke the synthesizer worker.

    ``InvocationType="Event"`` fires the worker and returns at once, so the POST answers
    within API Gateway's timeout; the worker moves the status to ``building`` and then
    ``ready``/``failed`` as it runs.
    """
    _write_status(tenant, {"status": "creating", "tenant": tenant})
    _lambda().invoke(
        FunctionName=os.environ["WORKER_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps({"tenant": tenant}).encode(),
    )


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


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Dispatch an API Gateway request: POST starts a create, GET reports status."""
    tenant = (event.get("pathParameters") or {}).get("tenant")
    if not tenant:
        return _response(404, {"error": "tenant required"})
    if event.get("httpMethod") == "POST":
        _start_create(tenant)
        return _response(202, {"status": "creating", "tenant": tenant})
    return _read_status(tenant)
