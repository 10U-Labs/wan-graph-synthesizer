"""Carriers read endpoint: serve a carrier's input graph from the S3 store.

    GET /wan-graph-designer/carriers                     -> the carrier ids
    GET /wan-graph-designer/carriers/{carrier}/vertices  -> that carrier's PoPs
    GET /wan-graph-designer/carriers/{carrier}/edges     -> that carrier's fiber

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


def _carrier_ids(client: Any) -> list[str]:
    """List the stored carrier ids (objects under the carriers/ prefix)."""
    listing = client.list_objects_v2(Bucket=os.environ["STORE_BUCKET"], Prefix="carriers/")
    return [
        item["Key"].removeprefix("carriers/").removesuffix(".json")
        for item in listing.get("Contents", [])
        if item["Key"].endswith(".json")
    ]


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Serve the carriers collection or one carrier's vertices/edges."""
    client = _s3()
    carrier = (event.get("pathParameters") or {}).get("carrier")
    if not carrier:
        return _response(200, _carrier_ids(client))
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection not in ("vertices", "edges"):
        return _response(404, {"error": collection})
    key = f"carriers/{carrier}.json"
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=key)["Body"].read()
    except client.exceptions.NoSuchKey:
        return _response(404, {"error": f"not built: {carrier}"})
    return _response(200, json.loads(body)[collection])
