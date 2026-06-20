"""CSPs read endpoint: serve a cloud provider's regions from the S3 store.

    GET /wan-graph-designer/csps                      -> the provider ids
    GET /wan-graph-designer/csps/{provider}/vertices  -> that provider's regions

A CSP graph is regions only (no fiber), so it exposes vertices but no edges.
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


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Serve the CSPs collection or one provider's regions (vertices)."""
    client = _s3()
    provider = (event.get("pathParameters") or {}).get("provider")
    if not provider:
        return _response(200, _provider_ids(client))
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection != "vertices":
        return _response(404, {"error": collection})
    key = f"csps/{provider}.json"
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=key)["Body"].read()
    except client.exceptions.NoSuchKey:
        return _response(404, {"error": f"not built: {provider}"})
    return _response(200, json.loads(body)[collection])
