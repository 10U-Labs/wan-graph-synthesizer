"""Carriers endpoint: read and write a carrier's input graph in the S3 store.

    GET    /wan-graph-designer/carriers                     -> the carrier ids
    GET    /wan-graph-designer/carriers/{carrier}/vertices  -> that carrier's PoPs
    GET    /wan-graph-designer/carriers/{carrier}/edges     -> that carrier's fiber
    PUT    /wan-graph-designer/carriers/{carrier}/vertices  -> replace its PoPs
    PUT    /wan-graph-designer/carriers/{carrier}/edges     -> replace its fiber
    DELETE /wan-graph-designer/carriers/{carrier}           -> remove the carrier

A write persists to the store and then auto-rebuilds the dependents (the carrier
merge is the shared substrate, so every customer's WAN depends on it): it invokes
the merge create and then a WAN create for each customer. Self-contained (stdlib +
boto3); deployed as a single-file Lambda.
"""

import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}


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
    """List the stored carrier ids (objects under the carriers/ prefix)."""
    listing = client.list_objects_v2(Bucket=os.environ["STORE_BUCKET"], Prefix="carriers/")
    return [
        item["Key"].removeprefix("carriers/").removesuffix(".json")
        for item in listing.get("Contents", [])
        if item["Key"].endswith(".json")
    ]


def _customer_ids(client: Any) -> list[str]:
    """List the customers (objects under customers/.../label.json, the marker doc)."""
    listing = client.list_objects_v2(
        Bucket=os.environ["STORE_BUCKET"], Prefix="customers/"
    )
    return [
        item["Key"].removeprefix("customers/").removesuffix("/label.json")
        for item in listing.get("Contents", [])
        if item["Key"].endswith("/label.json")
    ]


def _invoke(function: str, payload: dict[str, Any]) -> None:
    """Fire a downstream create Lambda asynchronously (fire-and-forget)."""
    _lambda().invoke(
        FunctionName=function, InvocationType="Event", Payload=json.dumps(payload).encode()
    )


def _cascade(client: Any) -> None:
    """Rebuild the substrate, then (re)create every customer's WAN."""
    _invoke(os.environ["MERGE_FUNCTION"], {"httpMethod": "POST"})
    for customer in _customer_ids(client):
        _invoke(
            os.environ["WAN_FUNCTION"],
            {"httpMethod": "POST", "pathParameters": {"customer": customer}},
        )


def _read_carrier(client: Any, carrier: str) -> Any:
    """Read a carrier's stored graph, or None when it is not built."""
    key = f"carriers/{carrier}.json"
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
    graph = _read_carrier(client, carrier)
    if graph is None:
        return _response(404, {"error": f"not built: {carrier}"})
    return _response(200, graph[collection])


def _put(client: Any, carrier: str, event: dict[str, Any]) -> dict[str, Any]:
    """Replace one of a carrier's collections, then cascade the rebuild."""
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection not in ("vertices", "edges"):
        return _response(404, {"error": collection})
    graph = _read_carrier(client, carrier) or {}
    graph[collection] = json.loads(event["body"])
    key = f"carriers/{carrier}.json"
    client.put_object(Bucket=os.environ["STORE_BUCKET"], Key=key, Body=json.dumps(graph).encode())
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
        client.delete_object(Bucket=os.environ["STORE_BUCKET"], Key=f"carriers/{carrier}.json")
        _cascade(client)
        return _response(200, {"deleted": carrier})
    return _put(client, carrier, event)
