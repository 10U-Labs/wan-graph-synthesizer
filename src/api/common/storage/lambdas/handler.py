import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}

_WORKING_PREFIXES = ("source/", "builds/")

_ONLY_VERSION = "null"

CARRIER_FILES = frozenset({"pops.json", "fiber-segments.json"})
PROVIDER_FILES = frozenset({"regions.json"})
TENANT_FILES = frozenset({
    "access-homing-degree.json",
    "backbone-node-count.json",
    "backbone-number-of-diverse-paths.json",
    "convergence-promotion.json",
    "degree-exempt-backbone-nodes.json",
    "forced-backbone-nodes.json",
    "forced-homes.json",
    "forced-paths.json",
    "knobs.json",
    "label.json",
    "locations.json",
    "off-net.json",
    "prohibited-backbone-nodes.json",
    "prohibited-paths.json",
    "provider-regions.json",
    "settings.json",
    "wan-status.json",
    "wan.json",
})
_KEPT_BY_PREFIX = {
    "carriers": CARRIER_FILES,
    "providers": PROVIDER_FILES,
    "tenants": TENANT_FILES,
}


def _s3() -> Any:
    if "s3" not in _CLIENTS:
        _CLIENTS["s3"] = boto3.client("s3", region_name="us-east-2")
    return _CLIENTS["s3"]


def clear_clients() -> None:
    _CLIENTS.clear()


def _response(status: int, body: Any) -> dict[str, Any]:
    return {"statusCode": status, "headers": dict(_HEADERS), "body": json.dumps(body)}


def is_current(key: str) -> bool:
    if key.startswith(_WORKING_PREFIXES):
        return True
    prefix, _, rest = key.partition("/")
    kept = _KEPT_BY_PREFIX.get(prefix)
    if kept is None or not rest:
        return False
    return rest.rsplit("/", 1)[-1] in kept


def _stale_keys(client: Any, bucket: str) -> list[str]:
    stale: list[str] = []
    token: str | None = None
    while True:
        page = (
            client.list_objects_v2(Bucket=bucket, ContinuationToken=token)
            if token
            else client.list_objects_v2(Bucket=bucket)
        )
        stale += [
            item["Key"] for item in page.get("Contents", []) if not is_current(item["Key"])
        ]
        token = page.get("NextContinuationToken")
        if not page.get("IsTruncated") or not token:
            return sorted(stale)


def _prune(client: Any) -> dict[str, Any]:
    bucket = os.environ["STORE_BUCKET"]
    deleted = _stale_keys(client, bucket)
    for key in deleted:
        client.delete_object(Bucket=bucket, Key=key, VersionId=_ONLY_VERSION)
    return {"deleted": deleted}


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    client = _s3()
    if event.get("httpMethod") == "POST":
        return _response(200, _prune(client))
    return _response(200, {"stale": _stale_keys(client, os.environ["STORE_BUCKET"])})
