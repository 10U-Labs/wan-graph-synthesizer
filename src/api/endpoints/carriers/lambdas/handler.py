"""Carriers endpoint: read and write a carrier's input graph in the S3 store.

    GET    /wan-graph-synthesizer/carriers                     -> the carrier ids
    GET    /wan-graph-synthesizer/carriers/{carrier}/vertices  -> that carrier's PoPs
    GET    /wan-graph-synthesizer/carriers/{carrier}/edges     -> that carrier's fiber
    PUT    /wan-graph-synthesizer/carriers/{carrier}/vertices  -> replace its PoPs
    PUT    /wan-graph-synthesizer/carriers/{carrier}/edges     -> replace its fiber
    DELETE /wan-graph-synthesizer/carriers/{carrier}           -> remove the carrier

A write persists to the store and then auto-rebuilds the dependents (the carrier
merge is the shared substrate, so every tenant's WAN depends on it): it invokes
the merge create and then a WAN create for each tenant. Self-contained (stdlib +
boto3); deployed as a single-file Lambda.
"""

import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
# A carrier's points and connections are bare geographic rows; reject anything else.
_VERTEX_FIELDS = {"municipality", "state", "latitude", "longitude"}
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


def _carrier_ids(client: Any) -> list[str]:
    """List the carrier ids: the first path segment under carriers/, minus the merge."""
    listing = client.list_objects_v2(Bucket=os.environ["STORE_BUCKET"], Prefix="carriers/")
    ids = {
        item["Key"].removeprefix("carriers/").split("/", 1)[0]
        for item in listing.get("Contents", [])
    }
    return sorted(ids - {"merge"})


def _tenant_ids(client: Any) -> list[str]:
    """List the tenants (objects under tenants/.../label.json, the marker doc)."""
    listing = client.list_objects_v2(
        Bucket=os.environ["STORE_BUCKET"], Prefix="tenants/"
    )
    return [
        item["Key"].removeprefix("tenants/").removesuffix("/label.json")
        for item in listing.get("Contents", [])
        if item["Key"].endswith("/label.json")
    ]


def _invoke(function: str, payload: dict[str, Any]) -> None:
    """Fire a downstream create Lambda asynchronously (fire-and-forget)."""
    _lambda().invoke(
        FunctionName=function, InvocationType="Event", Payload=json.dumps(payload).encode()
    )


def _cascade(client: Any) -> None:
    """Rebuild the substrate, then (re)create every tenant's WAN."""
    _invoke(os.environ["MERGE_FUNCTION"], {"httpMethod": "POST"})
    for tenant in _tenant_ids(client):
        _invoke(
            os.environ["WAN_FUNCTION"],
            {"httpMethod": "POST", "pathParameters": {"tenant": tenant}},
        )


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
    """Replace one of a carrier's collections (its own file), then cascade the rebuild."""
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection not in ("vertices", "edges"):
        return _response(404, {"error": collection})
    rows = json.loads(event["body"])
    error = _validate_rows(rows, _VERTEX_FIELDS if collection == "vertices" else _EDGE_FIELDS)
    if error:
        return _response(400, {"error": error})
    key = f"carriers/{carrier}/{collection}.json"
    client.put_object(Bucket=os.environ["STORE_BUCKET"], Key=key, Body=json.dumps(rows).encode())
    _cascade(client)
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
        _cascade(client)
        return _response(200, {"deleted": carrier})
    return _put(client, carrier, event)
