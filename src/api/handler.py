"""AWS Lambda entry point: serve the read endpoints from the S3 store.

API Gateway proxy integration. Routes ``/wan-graph-designer/<resource>/...`` to the
published graph JSON in the store and returns the requested collection, sliced via
``graph_collections``. One JSON format; CORS is open for the static site. A known
resource whose graph has not been built yet returns 404.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

import boto3

from wan_designer import graph_collections as gc

_CORS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}

# Customer (WAN) collections are sliced from the stored design payload; carrier/CSP
# inputs are already shaped as {"vertices", "edges"} so they pass through by key.
_CUSTOMER_SLICERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "vertices": gc.vertices,
    "edges": gc.edges,
    "core-nodes": gc.core_nodes,
    "aggregation-points": gc.aggregation_points,
    "access-nodes": gc.access_nodes,
}


def _response(status: int, body: Any) -> dict[str, Any]:
    """Build an API Gateway proxy response with open CORS."""
    return {"statusCode": status, "headers": dict(_CORS), "body": json.dumps(body)}


def _client() -> Any:
    """The real S3 client (region-pinned; constructed per invocation)."""
    return boto3.client("s3", region_name="us-east-2")


def _load(store: Any, key: str) -> dict[str, Any]:
    """Read and parse a published graph JSON object from the store."""
    raw = store.get_object(Bucket=os.environ["STORE_BUCKET"], Key=key)["Body"].read()
    parsed: dict[str, Any] = json.loads(raw)
    return parsed


def _resolve(parts: list[str]) -> tuple[str, Callable[[dict[str, Any]], Any]] | None:
    """Map a 3-part path to its (S3 key, collection slicer), or None if unknown."""
    if len(parts) != 3:
        return None
    resource, name, collection = parts
    if resource in ("carriers", "csps") and collection in ("vertices", "edges"):
        return f"{resource}/{name}.json", lambda payload: payload[collection]
    if resource == "customers" and collection in _CUSTOMER_SLICERS:
        return f"customers/{name}.json", _CUSTOMER_SLICERS[collection]
    return None


def dispatch(event: dict[str, Any], store: Any) -> dict[str, Any]:
    """Resolve the request path and serve the collection from the store."""
    proxy = (event.get("pathParameters") or {}).get("proxy", "")
    resolved = _resolve([part for part in proxy.split("/") if part])
    if resolved is None:
        return _response(404, {"error": f"not found: {proxy}"})
    key, slicer = resolved
    try:
        payload = _load(store, key)
    except store.exceptions.NoSuchKey:
        return _response(404, {"error": f"not built: {proxy}"})
    return _response(200, slicer(payload))


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Lambda entry point: serve a read request over the real S3 client."""
    return dispatch(event, _client())
