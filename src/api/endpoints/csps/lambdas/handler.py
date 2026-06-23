"""CSPs endpoint: read and write a cloud provider's regions in the S3 store.

    GET    /wan-graph-synthesizer/csps                      -> the provider ids
    GET    /wan-graph-synthesizer/csps/{provider}/vertices  -> that provider's regions
    PUT    /wan-graph-synthesizer/csps/{provider}/vertices  -> replace its regions
    DELETE /wan-graph-synthesizer/csps/{provider}           -> remove the provider

A CSP graph is regions only (no fiber), so it exposes vertices but no edges. CSP
regions are not part of the substrate, so a write does not rebuild the merge; it
re-creates every customer's WAN (a customer may select any provider's regions).
Self-contained (stdlib + boto3); deployed as a single-file Lambda.
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


def _provider_ids(client: Any) -> list[str]:
    """List the stored provider ids (objects under the csps/ prefix)."""
    listing = client.list_objects_v2(Bucket=os.environ["STORE_BUCKET"], Prefix="csps/")
    return [
        item["Key"].removeprefix("csps/").removesuffix(".json")
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


def _cascade(client: Any) -> None:
    """(Re)create every customer's WAN (any customer may use this provider)."""
    for customer in _customer_ids(client):
        _lambda().invoke(
            FunctionName=os.environ["WAN_FUNCTION"],
            InvocationType="Event",
            Payload=json.dumps(
                {"httpMethod": "POST", "pathParameters": {"customer": customer}}
            ).encode(),
        )


def _read_provider(client: Any, provider: str) -> Any:
    """Read a provider's stored graph, or None when it is not built."""
    key = f"csps/{provider}.json"
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=key)["Body"].read()
    except client.exceptions.NoSuchKey:
        return None
    return json.loads(body)


def _get(client: Any, provider: str | None, event: dict[str, Any]) -> dict[str, Any]:
    """Serve the CSPs collection or one provider's regions (vertices)."""
    if not provider:
        return _response(200, _provider_ids(client))
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection != "vertices":
        return _response(404, {"error": collection})
    graph = _read_provider(client, provider)
    if graph is None:
        return _response(404, {"error": f"not built: {provider}"})
    return _response(200, graph[collection])


def _put(client: Any, provider: str, event: dict[str, Any]) -> dict[str, Any]:
    """Replace a provider's regions, then cascade the rebuild."""
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection != "vertices":
        return _response(404, {"error": collection})
    graph = _read_provider(client, provider) or {}
    graph[collection] = json.loads(event["body"])
    key = f"csps/{provider}.json"
    client.put_object(Bucket=os.environ["STORE_BUCKET"], Key=key, Body=json.dumps(graph).encode())
    _cascade(client)
    return _response(200, {"updated": f"{provider}/{collection}"})


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Dispatch a CSPs request by method: read, replace, or delete."""
    client = _s3()
    method = event.get("httpMethod", "GET")
    provider = (event.get("pathParameters") or {}).get("provider")
    if method == "GET":
        return _get(client, provider, event)
    if not provider:
        return _response(404, {"error": "provider required"})
    if method == "DELETE":
        client.delete_object(Bucket=os.environ["STORE_BUCKET"], Key=f"csps/{provider}.json")
        _cascade(client)
        return _response(200, {"deleted": provider})
    return _put(client, provider, event)
