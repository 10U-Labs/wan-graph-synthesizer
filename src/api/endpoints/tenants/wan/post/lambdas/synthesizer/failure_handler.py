"""Failure handler: record a tenant's WAN as ``timeout`` when the synthesizer is killed.

The async ``on_failure`` destination for the synthesizer Lambda. AWS delivers the failed
invocation's event here only when the synthesizer did NOT return normally -- a wall-clock
timeout, an out-of-memory kill, or an unhandled crash -- none of which run the
synthesizer's own ``except`` block (a caught error is a normal return and never reaches
this handler). Read the tenant from the original request payload and write the terminal
``timeout`` status the dispatcher's GET serves as 422, so a build can never stay stuck on
``synthesizing`` forever.

``timeout`` rather than ``fail`` because the two endings ask the operator for opposite
things. ``fail`` is the synthesizer deciding no valid network is possible for this tenant,
which the tenant's ``etc/*.yml`` has to change before another run is worth starting;
reaching this handler says only that the run was cut off, which may well come out
differently next time and says nothing about the config.
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
    """Record ``timeout`` for the tenant whose synthesizer invocation was killed."""
    tenant = event["requestPayload"]["tenant"]
    status = {"status": "timeout", "reason": _reason(event)}
    boto3.client("s3", region_name="us-east-2").put_object(
        Bucket=os.environ["STORE_BUCKET"],
        Key=f"tenants/{tenant}/wan-status.json",
        Body=json.dumps(status).encode(),
    )
    return {"status": "timeout", "tenant": tenant}
