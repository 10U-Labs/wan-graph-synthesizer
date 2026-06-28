"""Carriers endpoint: read and write a carrier's input graph in the S3 store.

    GET    /wan-graph-synthesizer/carriers                     -> the carrier ids
    GET    /wan-graph-synthesizer/carriers/{carrier}/vertices  -> that carrier's PoPs
    GET    /wan-graph-synthesizer/carriers/{carrier}/edges     -> that carrier's fiber
    PUT    /wan-graph-synthesizer/carriers/{carrier}/vertices  -> replace its PoPs
    PUT    /wan-graph-synthesizer/carriers/{carrier}/edges     -> replace its fiber
    DELETE /wan-graph-synthesizer/carriers/{carrier}           -> remove the carrier

A write persists to the store and nothing else. Rebuilding the dependents (the carrier
merge substrate and each tenant's WAN) is done by explicit operations the caller invokes
(``POST /carriers/merge`` and ``POST /tenants/{t}/wan``), so a write endpoint never
triggers a build. Self-contained (stdlib + boto3); deployed as a single-file Lambda.
"""

import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
# A carrier's points and connections are bare geographic rows; reject anything else.
_VERTEX_FIELDS = {"municipality", "state", "country", "latitude", "longitude"}
_EDGE_FIELDS = {"a_municipality", "a_state", "z_municipality", "z_state"}


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


def _carrier_ids(client: Any) -> list[str]:
    """List the carrier ids: the first path segment under carriers/, minus the merge."""
    listing = client.list_objects_v2(Bucket=os.environ["STORE_BUCKET"], Prefix="carriers/")
    ids = {
        item["Key"].removeprefix("carriers/").split("/", 1)[0]
        for item in listing.get("Contents", [])
    }
    return sorted(ids - {"merge"})


def _read_collection(client: Any, carrier: str, collection: str) -> Any:
    """Read one of a carrier's stored row lists, or None when it is absent."""
    key = f"carriers/{carrier}/{collection}.json"
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=key)["Body"].read()
    except client.exceptions.NoSuchKey:
        return None
    return json.loads(body)


def _get(client: Any, carrier: str | None, event: dict[str, Any]) -> dict[str, Any]:
    """Serve the carriers collection or one carrier's vertices/edges."""
    if not carrier:
        return _response(200, _carrier_ids(client))
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection not in ("vertices", "edges"):
        return _response(404, {"error": collection})
    rows = _read_collection(client, carrier, collection)
    if rows is None:
        return _response(404, {"error": f"not built: {carrier}"})
    return _response(200, rows)


def _put(client: Any, carrier: str, event: dict[str, Any]) -> dict[str, Any]:
    """Replace one of a carrier's collections (its own file). Rebuilds are a separate POST."""
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection not in ("vertices", "edges"):
        return _response(404, {"error": collection})
    rows = json.loads(event["body"])
    error = _validate_rows(rows, _VERTEX_FIELDS if collection == "vertices" else _EDGE_FIELDS)
    if error:
        return _response(400, {"error": error})
    key = f"carriers/{carrier}/{collection}.json"
    client.put_object(Bucket=os.environ["STORE_BUCKET"], Key=key, Body=json.dumps(rows).encode())
    return _response(200, {"updated": f"{carrier}/{collection}"})


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Dispatch a carriers request by method: read, replace, or delete."""
    client = _s3()
    method = event.get("httpMethod", "GET")
    carrier = (event.get("pathParameters") or {}).get("carrier")
    if method == "GET":
        return _get(client, carrier, event)
    if not carrier:
        return _response(404, {"error": "carrier required"})
    if method == "DELETE":
        bucket = os.environ["STORE_BUCKET"]
        for collection in ("vertices", "edges"):
            client.delete_object(Bucket=bucket, Key=f"carriers/{carrier}/{collection}.json")
        return _response(200, {"deleted": carrier})
    return _put(client, carrier, event)
