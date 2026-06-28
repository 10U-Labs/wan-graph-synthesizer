"""Data-centers endpoint: read and write a colocation provider's facilities in the store.

    GET    /wan-graph-synthesizer/data-centers                      -> the provider ids
    GET    /wan-graph-synthesizer/data-centers/{provider}/vertices  -> that provider's sites
    PUT    /wan-graph-synthesizer/data-centers/{provider}/vertices  -> replace its sites
    DELETE /wan-graph-synthesizer/data-centers/{provider}           -> remove the provider

A data-center graph is facility points only (no fiber), so it exposes vertices but no
edges. The synthesizer never routes through these points -- they gate which carrier PoPs
may serve as backbone nodes (a backbone node must sit in a city a provider has a cage in).
A write only stores the sites; building a tenant's WAN is a separate operation
(``POST /tenants/{t}/wan``), so a write endpoint never triggers a build.
Self-contained (stdlib + boto3); deployed as a single-file Lambda.
"""

import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
# A provider's facilities are bare geographic rows (no name); reject anything else.
_VERTEX_FIELDS = {"municipality", "state", "country", "latitude", "longitude"}


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
    """List the provider ids: the first path segment under the data-centers/ prefix."""
    listing = client.list_objects_v2(Bucket=os.environ["STORE_BUCKET"], Prefix="data-centers/")
    return sorted({
        item["Key"].removeprefix("data-centers/").split("/", 1)[0]
        for item in listing.get("Contents", [])
    } - {"merge"})


def _read_sites(client: Any, provider: str) -> Any:
    """Read a provider's stored facilities (its vertices file), or None when absent."""
    key = f"data-centers/{provider}/vertices.json"
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=key)["Body"].read()
    except client.exceptions.NoSuchKey:
        return None
    return json.loads(body)


def _get(client: Any, provider: str | None, event: dict[str, Any]) -> dict[str, Any]:
    """Serve the data-centers collection or one provider's facilities (vertices)."""
    if not provider:
        return _response(200, _provider_ids(client))
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection != "vertices":
        return _response(404, {"error": collection})
    rows = _read_sites(client, provider)
    if rows is None:
        return _response(404, {"error": f"not built: {provider}"})
    return _response(200, rows)


def _put(client: Any, provider: str, event: dict[str, Any]) -> dict[str, Any]:
    """Replace a provider's facilities (its vertices file). Rebuilds are a separate POST."""
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection != "vertices":
        return _response(404, {"error": collection})
    rows = json.loads(event["body"])
    error = _validate_rows(rows, _VERTEX_FIELDS)
    if error:
        return _response(400, {"error": error})
    key = f"data-centers/{provider}/vertices.json"
    client.put_object(Bucket=os.environ["STORE_BUCKET"], Key=key, Body=json.dumps(rows).encode())
    return _response(200, {"updated": f"{provider}/{collection}"})


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Dispatch a data-centers request by method: read, replace, or delete."""
    client = _s3()
    method = event.get("httpMethod", "GET")
    provider = (event.get("pathParameters") or {}).get("provider")
    if method == "GET":
        return _get(client, provider, event)
    if not provider:
        return _response(404, {"error": "provider required"})
    if method == "DELETE":
        client.delete_object(
            Bucket=os.environ["STORE_BUCKET"], Key=f"data-centers/{provider}/vertices.json"
        )
        return _response(200, {"deleted": provider})
    return _put(client, provider, event)
