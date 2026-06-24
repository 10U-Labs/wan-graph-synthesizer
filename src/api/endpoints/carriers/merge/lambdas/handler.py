"""Carrier merge endpoint: stitch all carriers into the substrate (the shared mesh).

    POST /wan-graph-synthesizer/carriers/merge          -> (re)build the substrate
    GET  /wan-graph-synthesizer/carriers/merge/vertices -> the substrate's PoPs
    GET  /wan-graph-synthesizer/carriers/merge/edges    -> the substrate's fiber

The substrate is just every carrier's points and connections unioned, each row tagged
with the carrier it came from (taken from its endpoint path) so a connection resolves to
its own carrier's points. Cross-carrier colocation is resolved later, per tenant, by the
synthesizer. So the merge needs no design logic and stays a self-contained (stdlib +
boto3) single-file Lambda.
"""

import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
_MERGE_KEYS = {"vertices": "carriers/merge/vertices.json", "edges": "carriers/merge/edges.json"}


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


def _build_substrate(client: Any) -> dict[str, int]:
    """Union every carrier's points and connections (each tagged with its carrier).

    Reads ``carriers/{c}/vertices.json`` and ``carriers/{c}/edges.json`` for every
    carrier (skipping the merge's own output), stamps each row with its carrier id, and
    writes the two merged row lists. Returns their sizes.
    """
    bucket = os.environ["STORE_BUCKET"]
    listing = client.list_objects_v2(Bucket=bucket, Prefix="carriers/")
    vertices: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for item in listing.get("Contents", []):
        carrier, _, name = item["Key"].removeprefix("carriers/").partition("/")
        if carrier == "merge":
            continue
        rows = json.loads(client.get_object(Bucket=bucket, Key=item["Key"])["Body"].read())
        tagged = [{"carrier": carrier, **row} for row in rows]
        (vertices if name == "vertices.json" else edges).extend(tagged)
    client.put_object(
        Bucket=bucket, Key=_MERGE_KEYS["vertices"], Body=json.dumps(vertices).encode())
    client.put_object(
        Bucket=bucket, Key=_MERGE_KEYS["edges"], Body=json.dumps(edges).encode())
    return {"vertices": len(vertices), "edges": len(edges)}


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Build the substrate (POST) or serve one of its collections (GET)."""
    client = _s3()
    if event.get("httpMethod") == "POST":
        return _response(200, _build_substrate(client))
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection not in _MERGE_KEYS:
        return _response(404, {"error": collection})
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=_MERGE_KEYS[collection])
    except client.exceptions.NoSuchKey:
        return _response(404, {"error": "not built: substrate"})
    return _response(200, json.loads(body["Body"].read()))
