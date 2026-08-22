import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
_REGION_FIELDS = {"name", "municipality", "state", "country", "latitude", "longitude"}
_KEY = "providers/regions.json"


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


def _read_regions(client: Any) -> Any:
    try:
        body = client.get_object(Bucket=os.environ["STORE_BUCKET"], Key=_KEY)["Body"].read()
    except client.exceptions.NoSuchKey:
        return None
    return json.loads(body)


def _get(client: Any, event: dict[str, Any]) -> dict[str, Any]:
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection != "regions":
        return _response(404, {"error": collection})
    rows = _read_regions(client)
    if rows is None:
        return _response(404, {"error": "not built: providers"})
    return _response(200, rows)


def _put(client: Any, event: dict[str, Any]) -> dict[str, Any]:
    rows = json.loads(event["body"])
    error = _validate_rows(rows, _REGION_FIELDS)
    if error:
        return _response(400, {"error": error})
    client.put_object(Bucket=os.environ["STORE_BUCKET"], Key=_KEY, Body=json.dumps(rows).encode())
    return _response(200, {"updated": "providers/regions"})


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    client = _s3()
    method = event.get("httpMethod", "GET")
    if method == "GET":
        return _get(client, event)
    collection = event.get("path", "").rsplit("/", 1)[-1]
    if collection != "regions":
        return _response(404, {"error": collection})
    if method == "DELETE":
        client.delete_object(Bucket=os.environ["STORE_BUCKET"], Key=_KEY)
        return _response(200, {"deleted": "providers"})
    return _put(client, event)
