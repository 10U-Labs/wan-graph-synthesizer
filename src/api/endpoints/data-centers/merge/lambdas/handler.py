"""Data-centers merge endpoint: union every provider's facilities into one site set.

    POST /wan-graph-synthesizer/data-centers/merge -> (re)build the union
    GET  /wan-graph-synthesizer/data-centers/merge -> the union's facilities

The union is just every provider's facility points gathered together, each row tagged
with the provider it came from (taken from its endpoint path). The synthesizer reads this
one file to learn the data-center cities that gate which carrier PoPs may serve as
backbone nodes. Facilities carry no fiber, so there are no edges to merge -- the union is
a single collection, so its one resource both builds (POST) and serves (GET). Stays a
self-contained (stdlib + boto3) single-file Lambda.
"""

import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
_UNION_KEY = "data-centers/merge/vertices.json"


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


def _build_union(client: Any) -> dict[str, int]:
    """Union every provider's facilities (each tagged with its provider).

    Reads ``data-centers/{p}/vertices.json`` for every provider (skipping the merge's own
    output), stamps each row with its provider id, and writes the merged row list. Returns
    its size.
    """
    bucket = os.environ["STORE_BUCKET"]
    listing = client.list_objects_v2(Bucket=bucket, Prefix="data-centers/")
    vertices: list[dict[str, Any]] = []
    for item in listing.get("Contents", []):
        provider, _, name = item["Key"].removeprefix("data-centers/").partition("/")
        if provider == "merge" or name != "vertices.json":
            continue
        rows = json.loads(client.get_object(Bucket=bucket, Key=item["Key"])["Body"].read())
        vertices.extend({"provider": provider, **row} for row in rows)
    client.put_object(Bucket=bucket, Key=_UNION_KEY, Body=json.dumps(vertices).encode())
    return {"vertices": len(vertices)}


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Build the union (POST) or serve its facilities (GET).

    The union is a single collection, so GET reads it straight off ``/data-centers/merge``;
    a deeper sub-path is not a resource here and is a 404.
    """
    client = _s3()
    if event.get("httpMethod") == "POST":
        return _response(200, _build_union(client))
    if event.get("path", "").rstrip("/").rsplit("/", 1)[-1] != "merge":
        return _response(404, {"error": "not found"})
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=_UNION_KEY)
    except client.exceptions.NoSuchKey:
        return _response(404, {"error": "not built: union"})
    return _response(200, json.loads(body["Body"].read()))
