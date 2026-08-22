import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
_SITE_FIELDS = {"municipality", "state", "country", "latitude", "longitude"}
_LINK_FIELDS = {"a_municipality", "a_state", "z_municipality", "z_state", "submarine"}


def _validate_rows(body: Any, required: set[str]) -> str | None:
    if not isinstance(body, list):
        return "expected a list of rows"
    for row in body:
        if not isinstance(row, dict) or set(row) != required:
            return "each row must have exactly: " + ", ".join(sorted(required))
    return None


def _s3() -> Any:
    if "s3" not in _CLIENTS:
        _CLIENTS["s3"] = boto3.client("s3", region_name="us-east-2")
    return _CLIENTS["s3"]


def clear_clients() -> None:
    _CLIENTS.clear()


def _response(status: int, body: Any) -> dict[str, Any]:
    return {"statusCode": status, "headers": dict(_HEADERS), "body": json.dumps(body)}


def _carrier_ids(client: Any) -> list[str]:
    listing = client.list_objects_v2(Bucket=os.environ["STORE_BUCKET"], Prefix="carriers/")
    ids = {
        item["Key"].removeprefix("carriers/").split("/", 1)[0]
        for item in listing.get("Contents", [])
    }
    return sorted(ids - {"merge"})


def _read_collection(client: Any, carrier: str, collection: str) -> Any:
    key = f"carriers/{carrier}/{collection}.json"
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=key)["Body"].read()
    except client.exceptions.NoSuchKey:
        return None
    return json.loads(body)


def _get(client: Any, carrier: str | None, event: dict[str, Any]) -> dict[str, Any]:
    if not carrier:
        return _response(200, _carrier_ids(client))
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection not in ("pops", "fiber-segments"):
        return _response(404, {"error": collection})
    rows = _read_collection(client, carrier, collection)
    if rows is None:
        return _response(404, {"error": f"not built: {carrier}"})
    return _response(200, rows)


def _put(client: Any, carrier: str, event: dict[str, Any]) -> dict[str, Any]:
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection not in ("pops", "fiber-segments"):
        return _response(404, {"error": collection})
    rows = json.loads(event["body"])
    error = _validate_rows(rows, _SITE_FIELDS if collection == "pops" else _LINK_FIELDS)
    if error:
        return _response(400, {"error": error})
    key = f"carriers/{carrier}/{collection}.json"
    client.put_object(Bucket=os.environ["STORE_BUCKET"], Key=key, Body=json.dumps(rows).encode())
    return _response(200, {"updated": f"{carrier}/{collection}"})


def _delete(client: Any, carrier: str) -> dict[str, Any]:
    bucket = os.environ["STORE_BUCKET"]
    listing = client.list_objects_v2(Bucket=bucket, Prefix=f"carriers/{carrier}/")
    for item in listing.get("Contents", []):
        client.delete_object(Bucket=bucket, Key=item["Key"])
    return _response(200, {"deleted": carrier})


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    client = _s3()
    method = event.get("httpMethod", "GET")
    carrier = (event.get("pathParameters") or {}).get("carrier")
    if method == "GET":
        return _get(client, carrier, event)
    if not carrier:
        return _response(404, {"error": "carrier required"})
    if method == "DELETE":
        return _delete(client, carrier)
    return _put(client, carrier, event)
