"""WAN create endpoint: run a customer's synthesize on Fargate and report its status.

    POST /wan-graph-synthesizer/customers/{customer}/wan -> 202; start the create
    GET  /wan-graph-synthesizer/customers/{customer}/wan -> the WAN's status (422 if failed)

The synthesize math is slow, so a POST launches a Fargate task (the synthesizer container)
and returns immediately; the task writes the finished WAN and a status marker to S3. A
GET reads that marker -- 422 when no valid WAN was possible, 404 before the first create.
Self-contained (stdlib + boto3); single-file Lambda.
"""

import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}


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


def clear_clients() -> None:
    """Drop cached clients (tests reset between cases)."""
    _CLIENTS.clear()


def _response(status: int, body: Any) -> dict[str, Any]:
    """Build an API Gateway proxy response with open CORS."""
    return {"statusCode": status, "headers": dict(_HEADERS), "body": json.dumps(body)}


def _status_key(customer: str) -> str:
    """The S3 key holding a customer's WAN status marker."""
    return f"customers/{customer}/wan-status.json"


def _start_create(customer: str) -> None:
    """Mark the WAN as creating and launch the Fargate synthesizer task."""
    marker = json.dumps({"status": "creating", "customer": customer}).encode()
    _s3().put_object(
        Bucket=os.environ["STORE_BUCKET"], Key=_status_key(customer), Body=marker
    )
    _ecs().run_task(
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
                    {"name": "CUSTOMER", "value": customer}]}
            ]
        },
    )


def _read_status(customer: str) -> dict[str, Any]:
    """Serve a customer's WAN status: 422 when failed, 404 before any create."""
    client = _s3()
    try:
        body = client.get_object(
            Bucket=os.environ["STORE_BUCKET"], Key=_status_key(customer)
        )["Body"].read()
    except client.exceptions.NoSuchKey:
        return _response(404, {"error": f"no wan: {customer}"})
    status = json.loads(body)
    code = 422 if status.get("status") == "failed" else 200
    return _response(code, status)


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Start a WAN create (POST) or report a customer's WAN status (GET)."""
    customer = (event.get("pathParameters") or {}).get("customer")
    if not customer:
        return _response(404, {"error": "customer required"})
    if event.get("httpMethod") == "POST":
        _start_create(customer)
        return _response(202, {"status": "creating", "customer": customer})
    return _read_status(customer)
