"""Customers endpoint: read a computed WAN and read/write a customer's inputs.

    GET    /wan-graph-designer/customers                              -> [{id, label}]
    GET    /wan-graph-designer/customers/{c}/vertices|edges           -> the WAN graph
    GET    /wan-graph-designer/customers/{c}/core-nodes|...           -> the WAN tiers
    GET    /wan-graph-designer/customers/{c}/locations|forced-core-nodes|... -> an input
    PUT    /wan-graph-designer/customers/{c}/locations|forced-core-nodes|... -> set input
    DELETE /wan-graph-designer/customers/{c}                          -> remove the customer

The computed collections come from the published ``wan.json``; each operator input is
its own document (the optimizer reads them all). A PUT persists the input and
re-creates this customer's WAN. Self-contained (stdlib + boto3); single-file Lambda.
"""

import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
_WAN_COLLECTIONS = ("vertices", "edges", "core-nodes", "aggregation-points", "access-nodes")
# Each operator input is its own resource, stored as ``<collection>.json``. The former
# ``config`` document is decomposed into the per-concern resources below.
_INPUTS = frozenset({
    "locations",
    "csp-regions",
    "off-net",
    "forced-core-nodes",
    "forced-aggregation-points",
    "forced-connections",
    "prohibited-core-nodes",
    "prohibited-aggregation-points",
    "prohibited-connections",
    "core-node-count",
    "core-mesh-degree",
    "aggregation-homing-degree",
    "access-homing-degree",
    "knobs",
    "label",
})
# Customers are enumerated by this marker document (every customer has a label).
_CUSTOMER_MARKER = "label.json"


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


def _customers(client: Any) -> list[dict[str, str]]:
    """List the customers (those with a label) as ``{id, label}`` entries for the UI.

    The display label is the customer's ``label`` document (e.g. ``F-35 (redundant)``),
    falling back to the id when it is unset.
    """
    listing = client.list_objects_v2(
        Bucket=os.environ["STORE_BUCKET"], Prefix="customers/"
    )
    customers = []
    for item in listing.get("Contents", []):
        key = item["Key"]
        if not key.endswith(f"/{_CUSTOMER_MARKER}"):
            continue
        customer = key.removeprefix("customers/").removesuffix(f"/{_CUSTOMER_MARKER}")
        label = _read_object(client, key) or {}
        customers.append({"id": customer, "label": label.get("label") or customer})
    return customers


def _read_object(client: Any, key: str) -> Any:
    """Read and decode a stored object, or None when it is absent."""
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=key)["Body"].read()
    except client.exceptions.NoSuchKey:
        return None
    return json.loads(body)


def _serve(client: Any, customer: str, key: str, field: str | None = None) -> dict[str, Any]:
    """Serve a stored document (or one field of it), or 404 when it is absent."""
    doc = _read_object(client, key)
    if doc is None:
        return _response(404, {"error": f"not built: {customer}"})
    return _response(200, doc if field is None else doc[field])


def _cascade(customer: str) -> None:
    """Re-create this customer's WAN after an input change."""
    _lambda().invoke(
        FunctionName=os.environ["WAN_FUNCTION"],
        InvocationType="Event",
        Payload=json.dumps(
            {"httpMethod": "POST", "pathParameters": {"customer": customer}}
        ).encode(),
    )


def _get(client: Any, customer: str | None, event: dict[str, Any]) -> dict[str, Any]:
    """Serve the customers collection, a WAN collection, or an input document."""
    if not customer:
        return _response(200, _customers(client))
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection in _WAN_COLLECTIONS:
        return _serve(client, customer, f"customers/{customer}/wan.json", collection)
    if collection in _INPUTS:
        return _serve(client, customer, f"customers/{customer}/{collection}.json")
    return _response(404, {"error": collection})


def _put(client: Any, customer: str, event: dict[str, Any]) -> dict[str, Any]:
    """Replace one of a customer's input documents, then re-create its WAN."""
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection not in _INPUTS:
        return _response(404, {"error": collection})
    key = f"customers/{customer}/{collection}.json"
    body = json.dumps(json.loads(event["body"])).encode()
    client.put_object(Bucket=os.environ["STORE_BUCKET"], Key=key, Body=body)
    _cascade(customer)
    return _response(200, {"updated": f"{customer}/{collection}"})


def _delete(client: Any, customer: str) -> dict[str, Any]:
    """Remove every object belonging to a customer."""
    bucket = os.environ["STORE_BUCKET"]
    listing = client.list_objects_v2(Bucket=bucket, Prefix=f"customers/{customer}/")
    for item in listing.get("Contents", []):
        client.delete_object(Bucket=bucket, Key=item["Key"])
    return _response(200, {"deleted": customer})


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Dispatch a customers request by method: read, replace an input, or delete."""
    client = _s3()
    method = event.get("httpMethod", "GET")
    customer = (event.get("pathParameters") or {}).get("customer")
    if method == "GET":
        return _get(client, customer, event)
    if not customer:
        return _response(404, {"error": "customer required"})
    if method == "DELETE":
        return _delete(client, customer)
    return _put(client, customer, event)
