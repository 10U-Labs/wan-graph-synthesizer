"""Failure handler: record a tenant's WAN as ``failed`` when the synthesizer dies.

The async ``on_failure`` destination for the synthesizer Lambda. AWS delivers the failed
invocation's event here only when the synthesizer did NOT return normally -- a wall-clock
timeout, an out-of-memory kill, or an unhandled crash -- none of which run the
synthesizer's own ``except`` block (a caught error is a normal return and never reaches
this handler). Read the tenant from the original request payload and write the terminal
``failed`` status the dispatcher's GET serves as 422, so a build can never stay stuck on
``building`` forever.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3


def _reason(event: dict[str, Any]) -> str:
    """Summarise why the synthesizer invocation failed, for the status marker."""
    condition = event.get("requestContext", {}).get("condition")
    if condition:
        return f"synthesizer invocation failed ({condition})"
    return "synthesizer terminated before completing (timed out or crashed)"


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Record ``failed`` for the tenant whose synthesizer invocation died."""
    tenant = event["requestPayload"]["tenant"]
    status = {"status": "failed", "reason": _reason(event)}
    boto3.client("s3", region_name="us-east-2").put_object(
        Bucket=os.environ["STORE_BUCKET"],
        Key=f"tenants/{tenant}/wan-status.json",
        Body=json.dumps(status).encode(),
    )
    return {"status": "failed", "tenant": tenant}
