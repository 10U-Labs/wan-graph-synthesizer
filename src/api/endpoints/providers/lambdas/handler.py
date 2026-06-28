"""providers endpoint: read and write a cloud provider's regions in the S3 store.

    GET    /wan-graph-synthesizer/providers                      -> the provider ids
    GET    /wan-graph-synthesizer/providers/{provider}/vertices  -> that provider's regions
    PUT    /wan-graph-synthesizer/providers/{provider}/vertices  -> replace its regions
    DELETE /wan-graph-synthesizer/providers/{provider}           -> remove the provider

A provider graph is regions only (no fiber), so it exposes vertices but no edges. A write
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
# A provider's regions are named geographic rows; reject anything else.
_REGION_FIELDS = {"name", "municipality", "state", "country", "latitude", "longitude"}


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


def _provider_ids(client: Any) -> list[str]:
    """List the provider ids: the first path segment under the providers/ prefix."""
    listing = client.list_objects_v2(Bucket=os.environ["STORE_BUCKET"], Prefix="providers/")
    return sorted({
        item["Key"].removeprefix("providers/").split("/", 1)[0]
        for item in listing.get("Contents", [])
    })


def _read_regions(client: Any, provider: str) -> Any:
    """Read a provider's stored regions (its vertices file), or None when absent."""
    key = f"providers/{provider}/vertices.json"
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=key)["Body"].read()
    except client.exceptions.NoSuchKey:
        return None
    return json.loads(body)


def _get(client: Any, provider: str | None, event: dict[str, Any]) -> dict[str, Any]:
    """Serve the providers collection or one provider's regions (vertices)."""
    if not provider:
        return _response(200, _provider_ids(client))
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection != "vertices":
        return _response(404, {"error": collection})
    rows = _read_regions(client, provider)
    if rows is None:
        return _response(404, {"error": f"not built: {provider}"})
    return _response(200, rows)


def _put(client: Any, provider: str, event: dict[str, Any]) -> dict[str, Any]:
    """Replace a provider's regions (its vertices file). Rebuilds are a separate POST."""
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection != "vertices":
        return _response(404, {"error": collection})
    rows = json.loads(event["body"])
    error = _validate_rows(rows, _REGION_FIELDS)
    if error:
        return _response(400, {"error": error})
    key = f"providers/{provider}/vertices.json"
    client.put_object(Bucket=os.environ["STORE_BUCKET"], Key=key, Body=json.dumps(rows).encode())
    return _response(200, {"updated": f"{provider}/{collection}"})


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Dispatch a providers request by method: read, replace, or delete."""
    client = _s3()
    method = event.get("httpMethod", "GET")
    provider = (event.get("pathParameters") or {}).get("provider")
    if method == "GET":
        return _get(client, provider, event)
    if not provider:
        return _response(404, {"error": "provider required"})
    if method == "DELETE":
        client.delete_object(
            Bucket=os.environ["STORE_BUCKET"], Key=f"providers/{provider}/vertices.json"
        )
        return _response(200, {"deleted": provider})
    return _put(client, provider, event)
