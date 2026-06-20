"""Customers read endpoint: serve a customer's computed WAN from the S3 store.

    GET /wan-graph-designer/customers                              -> the customer ids
    GET /wan-graph-designer/customers/{customer}/vertices          -> the WAN's vertices
    GET /wan-graph-designer/customers/{customer}/edges             -> the WAN's edges
    GET /wan-graph-designer/customers/{customer}/core-nodes        -> the core tier
    GET /wan-graph-designer/customers/{customer}/aggregation-points-> the aggregation tier
    GET /wan-graph-designer/customers/{customer}/access-nodes      -> the access tier

The create task writes the WAN pre-shaped into these collections; this read Lambda
just serves the requested one. Self-contained (stdlib + boto3); single-file Lambda.
"""

import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
_COLLECTIONS = ("vertices", "edges", "core-nodes", "aggregation-points", "access-nodes")


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


def _customer_ids(client: Any) -> list[str]:
    """List the stored customer ids (WAN objects under the customers/ prefix)."""
    listing = client.list_objects_v2(
        Bucket=os.environ["STORE_BUCKET"], Prefix="customers/"
    )
    return [
        item["Key"].removeprefix("customers/").removesuffix("/wan.json")
        for item in listing.get("Contents", [])
        if item["Key"].endswith("/wan.json")
    ]


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Serve the customers collection or one customer WAN's collection."""
    client = _s3()
    customer = (event.get("pathParameters") or {}).get("customer")
    if not customer:
        return _response(200, _customer_ids(client))
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection not in _COLLECTIONS:
        return _response(404, {"error": collection})
    key = f"customers/{customer}/wan.json"
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=key)["Body"].read()
    except client.exceptions.NoSuchKey:
        return _response(404, {"error": f"not built: {customer}"})
    return _response(200, json.loads(body)[collection])
