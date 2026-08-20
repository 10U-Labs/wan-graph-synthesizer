"""Carrier merge endpoint: draw every carrier's PoPs and fiber on one map.

    POST /wan-synthesizer/carriers/merge          -> (re)build the merged carriers
    GET  /wan-synthesizer/carriers/merge/pops -> the merged carriers' PoPs
    GET  /wan-synthesizer/carriers/merge/fiber-segments    -> the merged carriers' fiber

The merged carriers are just every carrier's points and fiber segments unioned, each row
tagged with the carrier it came from (taken from its endpoint path) so a segment resolves
to its own carrier's points. Cross-carrier colocation is resolved later, per tenant, by the
synthesizer. So the merge needs no synthesis logic and stays a self-contained (stdlib +
boto3) single-file Lambda.
"""

import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
_MERGE_KEYS = {
    "pops": "carriers/merge/pops.json",
    "fiber-segments": "carriers/merge/fiber-segments.json",
}
# The only two file names a carrier stores under. Anything else under carriers/ is
# not one of them and is left alone: a leftover from an older name would otherwise be
# merged in as fiber and every synthesis would fail on the columns it does not carry.
_CARRIER_FILES = ("pops.json", "fiber-segments.json")


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


def _build_merged_carriers(client: Any) -> dict[str, int]:
    """Union every carrier's points and fiber segments (each tagged with its carrier).

    Reads ``carriers/{c}/pops.json`` and ``carriers/{c}/fiber-segments.json`` for every
    carrier, skipping the merge's own output and any other file under ``carriers/``,
    stamps each row with its carrier id, and writes the two merged row lists. Returns
    their sizes.
    """
    bucket = os.environ["STORE_BUCKET"]
    listing = client.list_objects_v2(Bucket=bucket, Prefix="carriers/")
    pops: list[dict[str, Any]] = []
    fiber_segments: list[dict[str, Any]] = []
    for item in listing.get("Contents", []):
        carrier, _, name = item["Key"].removeprefix("carriers/").partition("/")
        if carrier == "merge" or name not in _CARRIER_FILES:
            continue
        rows = json.loads(client.get_object(Bucket=bucket, Key=item["Key"])["Body"].read())
        tagged = [{"carrier": carrier, **row} for row in rows]
        (pops if name == "pops.json" else fiber_segments).extend(tagged)
    client.put_object(
        Bucket=bucket, Key=_MERGE_KEYS["pops"], Body=json.dumps(pops).encode())
    client.put_object(
        Bucket=bucket, Key=_MERGE_KEYS["fiber-segments"], Body=json.dumps(fiber_segments).encode())
    return {"pops": len(pops), "fiber-segments": len(fiber_segments)}


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Build the merged carriers (POST) or serve one of their collections (GET)."""
    client = _s3()
    if event.get("httpMethod") == "POST":
        return _response(200, _build_merged_carriers(client))
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection not in _MERGE_KEYS:
        return _response(404, {"error": collection})
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=_MERGE_KEYS[collection])
    except client.exceptions.NoSuchKey:
        return _response(404, {"error": "not built: merged carriers"})
    return _response(200, json.loads(body["Body"].read()))
