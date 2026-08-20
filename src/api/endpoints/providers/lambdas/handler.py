"""Providers endpoint: read and write the provider regions in the S3 store.

    GET    /wan-graph-synthesizer/providers/regions  -> the provider regions
    PUT    /wan-graph-synthesizer/providers/regions  -> replace the regions
    DELETE /wan-graph-synthesizer/providers/regions  -> remove the regions

A provider graph is regions only (no fiber), so it exposes sites but no links. A write
only stores the regions; building a tenant's WAN is a separate operation
(``POST /tenants/{t}/wan``), so a write endpoint never triggers a build.
Self-contained (stdlib + boto3); deployed as a single-file Lambda.
"""

import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
# The provider regions are named geographic rows; reject anything else.
_REGION_FIELDS = {"name", "municipality", "state", "country", "latitude", "longitude"}
# The regions live in a single stored object (there is one provider set).
_KEY = "providers/regions.json"


def _validate_rows(body: Any, required: set[str]) -> str | None:
    """Return an error message if body is not a list of rows each having exactly the fields."""
    if not isinstance(body, list):
        return "expected a list of rows"
    for row in body:
        if not isinstance(row, dict) or set(row) != required:
            return "each row must have exactly: " + ", ".join(sorted(required))
    return None


def _s3() -> Any:
    """Return the cached S3 client, creating it on first use."""
    if "s3" not in _CLIENTS:
        _CLIENTS["s3"] = boto3.client("s3", region_name="us-east-2")
    return _CLIENTS["s3"]


def clear_clients() -> None:
    """Drop cached clients (tests reset between cases)."""
    _CLIENTS.clear()


def _response(status: int, body: Any) -> dict[str, Any]:
    """Build an API Gateway proxy response with open CORS."""
    return {"statusCode": status, "headers": dict(_HEADERS), "body": json.dumps(body)}


def _read_regions(client: Any) -> Any:
    """Read the stored provider regions (the sites file), or None when absent."""
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=_KEY)["Body"].read()
    except client.exceptions.NoSuchKey:
        return None
    return json.loads(body)


def _get(client: Any, event: dict[str, Any]) -> dict[str, Any]:
    """Serve the provider regions (sites)."""
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection != "regions":
        return _response(404, {"error": collection})
    rows = _read_regions(client)
    if rows is None:
        return _response(404, {"error": "not built: providers"})
    return _response(200, rows)


def _put(client: Any, event: dict[str, Any]) -> dict[str, Any]:
    """Replace the provider regions (the sites file). Rebuilds are a separate POST.

    The caller (``lambda_handler``) has already confirmed the collection is ``sites``.
    """
    rows = json.loads(event["body"])
    error = _validate_rows(rows, _REGION_FIELDS)
    if error:
        return _response(400, {"error": error})
    client.put_object(Bucket=os.environ["STORE_BUCKET"], Key=_KEY, Body=json.dumps(rows).encode())
    return _response(200, {"updated": "providers/regions"})


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Dispatch a providers request by method: read, replace, or delete the regions."""
    client = _s3()
    method = event.get("httpMethod", "GET")
    if method == "GET":
        return _get(client, event)
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection != "regions":
        return _response(404, {"error": collection})
    if method == "DELETE":
        client.delete_object(Bucket=os.environ["STORE_BUCKET"], Key=_KEY)
        return _response(200, {"deleted": "providers"})
    return _put(client, event)
