from __future__ import annotations

import json
import os
from typing import Any

import boto3


def _reason(event: dict[str, Any]) -> str:
    condition = event.get("requestContext", {}).get("condition")
    if condition:
        return f"synthesizer invocation failed ({condition})"
    return "synthesizer terminated before completing (timed out or crashed)"


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    tenant = event["requestPayload"]["tenant"]
    status = {"status": "timeout", "reason": _reason(event)}
    boto3.client("s3", region_name="us-east-2").put_object(
        Bucket=os.environ["STORE_BUCKET"],
        Key=f"tenants/{tenant}/wan-status.json",
        Body=json.dumps(status).encode(),
    )
    return {"status": "timeout", "tenant": tenant}
