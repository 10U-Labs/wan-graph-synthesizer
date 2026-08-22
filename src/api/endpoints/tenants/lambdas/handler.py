import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
_WAN_COLLECTIONS = (
    "sites",
    "paths",
    "backbone-nodes",
    "backbone-links",
    "tenant-nodes",
    "provider-nodes",
)
_INPUTS = frozenset({
    "locations",
    "provider-regions",
    "off-net",
    "forced-backbone-nodes",
    "forced-paths",
    "forced-homes",
    "prohibited-backbone-nodes",
    "prohibited-paths",
    "degree-exempt-backbone-nodes",
    "backbone-node-count",
    "backbone-number-of-diverse-paths",
    "access-homing-degree",
    "convergence-promotion",
    "knobs",
    "settings",
    "label",
})
_TENANT_MARKER = "label.json"
_SITE_FIELDS = {"name", "municipality", "state", "country", "latitude", "longitude"}
_LOCATION_FIELDS = _SITE_FIELDS | {"exemptfromdistanceconstraint"}
_SITE_INPUT_FIELDS = {
    "locations": _LOCATION_FIELDS,
    "provider-regions": _SITE_FIELDS,
    "off-net": {"municipality", "state", "country", "latitude", "longitude"},
}


def _validate_rows(body: Any, required: set[str]) -> str | None:
    if not isinstance(body, list):
        return "expected a list of rows"
    for row in body:
        if not isinstance(row, dict) or not required.issubset(row):
            return "each row must have at least: " + ", ".join(sorted(required))
    return None


def _s3() -> Any:
    if "s3" not in _CLIENTS:
        _CLIENTS["s3"] = boto3.client("s3", region_name="us-east-2")
    return _CLIENTS["s3"]


def clear_clients() -> None:
    _CLIENTS.clear()


def _response(status: int, body: Any) -> dict[str, Any]:
    return {"statusCode": status, "headers": dict(_HEADERS), "body": json.dumps(body)}


def _tenants(client: Any) -> list[dict[str, str]]:
    listing = client.list_objects_v2(
        Bucket=os.environ["STORE_BUCKET"], Prefix="tenants/"
    )
    tenants = []
    for item in listing.get("Contents", []):
        key = item["Key"]
        if not key.endswith(f"/{_TENANT_MARKER}"):
            continue
        tenant = key.removeprefix("tenants/").removesuffix(f"/{_TENANT_MARKER}")
        label = _read_object(client, key) or {}
        tenants.append({"id": tenant, "label": label.get("label") or tenant})
    return tenants


def _read_object(client: Any, key: str) -> Any:
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=key)["Body"].read()
    except client.exceptions.NoSuchKey:
        return None
    return json.loads(body)


def _serve(client: Any, tenant: str, key: str, field: str | None = None) -> dict[str, Any]:
    doc = _read_object(client, key)
    if doc is None:
        return _response(404, {"error": f"not built: {tenant}"})
    return _response(200, doc if field is None else doc[field])


def _get(client: Any, tenant: str | None, event: dict[str, Any]) -> dict[str, Any]:
    if not tenant:
        return _response(200, _tenants(client))
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection in _WAN_COLLECTIONS:
        return _serve(client, tenant, f"tenants/{tenant}/wan.json", collection)
    if collection in _INPUTS:
        return _serve(client, tenant, f"tenants/{tenant}/{collection}.json")
    return _response(404, {"error": collection})


def _put(client: Any, tenant: str, event: dict[str, Any]) -> dict[str, Any]:
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection not in _INPUTS:
        return _response(404, {"error": collection})
    document = json.loads(event["body"])
    fields = _SITE_INPUT_FIELDS.get(collection)
    if fields is not None:
        error = _validate_rows(document, fields)
        if error:
            return _response(400, {"error": error})
    key = f"tenants/{tenant}/{collection}.json"
    client.put_object(
        Bucket=os.environ["STORE_BUCKET"], Key=key, Body=json.dumps(document).encode())
    return _response(200, {"updated": f"{tenant}/{collection}"})


def _delete(client: Any, tenant: str) -> dict[str, Any]:
    bucket = os.environ["STORE_BUCKET"]
    listing = client.list_objects_v2(Bucket=bucket, Prefix=f"tenants/{tenant}/")
    for item in listing.get("Contents", []):
        client.delete_object(Bucket=bucket, Key=item["Key"])
    return _response(200, {"deleted": tenant})


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    client = _s3()
    method = event.get("httpMethod", "GET")
    tenant = (event.get("pathParameters") or {}).get("tenant")
    if method == "GET":
        return _get(client, tenant, event)
    if not tenant:
        return _response(404, {"error": "tenant required"})
    if method == "DELETE":
        return _delete(client, tenant)
    return _put(client, tenant, event)
