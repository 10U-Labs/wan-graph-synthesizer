"""Tenants endpoint: read a computed WAN and read/write a tenant's inputs.

    GET    /wan-graph-synthesizer/tenants                              -> [{id, label}]
    GET    /wan-graph-synthesizer/tenants/{c}/vertices|edges           -> the WAN graph
    GET    /wan-graph-synthesizer/tenants/{c}/backbone-nodes|...        -> the WAN tiers
    GET    /wan-graph-synthesizer/tenants/{c}/backbone-links            -> the WAN mesh links
    GET    /wan-graph-synthesizer/tenants/{c}/locations|forced-backbone-nodes|... -> an input
    PUT    /wan-graph-synthesizer/tenants/{c}/locations|forced-backbone-nodes|... -> set input
    DELETE /wan-graph-synthesizer/tenants/{c}                          -> remove the tenant

The computed collections come from the published ``wan.json``; each operator input is
its own document (the synthesizer reads them all). A PUT persists the input and nothing
else: building the WAN is a separate operation (``POST /tenants/{c}/wan``), so a write
endpoint never triggers a build. Self-contained (stdlib + boto3); single-file Lambda.
"""

import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
_WAN_COLLECTIONS = (
    "vertices",
    "edges",
    "backbone-nodes",
    "backbone-links",
    "tenant-nodes",
    "provider-nodes",
)
# Each operator input is its own resource, stored as ``<collection>.json``. The former
# ``config`` document is decomposed into the per-concern resources below.
_INPUTS = frozenset({
    "locations",
    "provider-regions",
    "off-net",
    "forced-backbone-nodes",
    "forced-connections",
    "forced-homes",
    "prohibited-backbone-nodes",
    "prohibited-connections",
    "backbone-node-count",
    "backbone-mesh-degree",
    "access-homing-degree",
    "backbone-placement",
    "convergence-promotion",
    "knobs",
    "settings",
    "label",
})
# Tenants are enumerated by this marker document (every tenant has a label).
_TENANT_MARKER = "label.json"
# The vertex-list inputs are geographic rows with a known set of required fields; the
# remaining config resources (forced-*, degrees, knobs, settings, label) are validated
# only by the schema their consumers expect, so they pass through unchecked here. A row may carry
# extra fields beyond the required set -- only tenant locations must additionally carry
# the ``exemptfromdistanceconstraint`` column (cloud regions and off-net do not).
_SITE_FIELDS = {"name", "municipality", "state", "country", "latitude", "longitude"}
_LOCATION_FIELDS = _SITE_FIELDS | {"exemptfromdistanceconstraint"}
_VERTEX_INPUT_FIELDS = {
    "locations": _LOCATION_FIELDS,
    "provider-regions": _SITE_FIELDS,
    "off-net": {"municipality", "state", "country", "latitude", "longitude"},
}


def _validate_rows(body: Any, required: set[str]) -> str | None:
    """Return an error message if body is not a list of rows each containing the fields.

    A row must have at least the required fields; extra fields are allowed.
    """
    if not isinstance(body, list):
        return "expected a list of rows"
    for row in body:
        if not isinstance(row, dict) or not required.issubset(row):
            return "each row must have at least: " + ", ".join(sorted(required))
    return None


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


def _tenants(client: Any) -> list[dict[str, str]]:
    """List the tenants (those with a label) as ``{id, label}`` entries for the UI.

    The display label is the tenant's ``label`` document (e.g. ``F-35``),
    falling back to the id when it is unset.
    """
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
    """Read and decode a stored object, or None when it is absent."""
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=key)["Body"].read()
    except client.exceptions.NoSuchKey:
        return None
    return json.loads(body)


def _serve(client: Any, tenant: str, key: str, field: str | None = None) -> dict[str, Any]:
    """Serve a stored document (or one field of it), or 404 when it is absent."""
    doc = _read_object(client, key)
    if doc is None:
        return _response(404, {"error": f"not built: {tenant}"})
    return _response(200, doc if field is None else doc[field])


def _get(client: Any, tenant: str | None, event: dict[str, Any]) -> dict[str, Any]:
    """Serve the tenants collection, a WAN collection, or an input document."""
    if not tenant:
        return _response(200, _tenants(client))
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection in _WAN_COLLECTIONS:
        return _serve(client, tenant, f"tenants/{tenant}/wan.json", collection)
    if collection in _INPUTS:
        return _serve(client, tenant, f"tenants/{tenant}/{collection}.json")
    return _response(404, {"error": collection})


def _put(client: Any, tenant: str, event: dict[str, Any]) -> dict[str, Any]:
    """Replace one of a tenant's input documents. Building the WAN is a separate POST."""
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection not in _INPUTS:
        return _response(404, {"error": collection})
    document = json.loads(event["body"])
    fields = _VERTEX_INPUT_FIELDS.get(collection)
    if fields is not None:
        error = _validate_rows(document, fields)
        if error:
            return _response(400, {"error": error})
    key = f"tenants/{tenant}/{collection}.json"
    client.put_object(
        Bucket=os.environ["STORE_BUCKET"], Key=key, Body=json.dumps(document).encode())
    return _response(200, {"updated": f"{tenant}/{collection}"})


def _delete(client: Any, tenant: str) -> dict[str, Any]:
    """Remove every object belonging to a tenant."""
    bucket = os.environ["STORE_BUCKET"]
    listing = client.list_objects_v2(Bucket=bucket, Prefix=f"tenants/{tenant}/")
    for item in listing.get("Contents", []):
        client.delete_object(Bucket=bucket, Key=item["Key"])
    return _response(200, {"deleted": tenant})


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Dispatch a tenants request by method: read, replace an input, or delete."""
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
