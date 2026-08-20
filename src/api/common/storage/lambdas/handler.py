"""Store prune endpoint: take out the objects no endpoint serves any more.

    POST /wan-synthesizer/store/prune  -> delete every object stored under a name the
                                          product no longer writes, and name what went

Renaming a collection writes the new key and leaves the old one where it is, because every
writer replaces the key it names and nothing asks what else is under the prefix. The
leftovers are not inert: a reader that lists a prefix meets them as though they were
current, which is how ``carriers/lumen/vertices.json`` came to be merged in as fiber and
failed every tenant's build on 2026-08-20 (GitHub issue #102).

What is current is written down here, one set per prefix, and everything else under those
prefixes goes. A prefix this endpoint has never heard of goes whole, which is what takes
out the retired ``csps/`` and ``data-centers/`` objects that no endpoint can reach because
their stacks were deleted. The two working areas are left alone: ``source/`` holds the
git-authored inputs and ``builds/`` the per-create artifacts the bucket's own lifecycle
rule expires.

Everything it deletes, ``scripts/seed.py`` can put back: the seed PUTs every carrier,
provider and tenant input from ``data/`` and ``etc/`` and then POSTs one build per tenant,
so a prune that took too much costs a re-seed rather than the data. Self-contained
(stdlib + boto3); deployed as a single-file Lambda.
"""

import json
import os
from typing import Any

import boto3

_CLIENTS: dict[str, Any] = {}
_HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}

# The working areas, left alone whatever they hold: git-authored inputs pushed through the
# API, and the per-create artifacts the store's own lifecycle rule expires after 14 days.
_WORKING_PREFIXES = ("source/", "builds/")

# The version every object in the store carries. Versioning is suspended on the bucket, so
# there is exactly one of each key and S3 calls its version "null"; naming it on a delete
# is what removes the object rather than writing a delete marker over it.
_ONLY_VERSION = "null"

# One set per prefix: the file names the product writes there today. A key under one of
# these prefixes whose file name is not in its set is a collection that has been renamed
# out from under it, and is what this endpoint is for. The three are public because they
# are this endpoint's answer to what the store legitimately holds, and the contract test in
# test/api/common/storage/pre_deployment/integration/ reads them to hold that answer
# against the routes src/www/api/openapi.json declares.
CARRIER_FILES = frozenset({"pops.json", "fiber-segments.json"})
PROVIDER_FILES = frozenset({"regions.json"})
# The tenant inputs are ``_INPUTS`` in src/api/endpoints/tenants/lambdas/handler.py, one
# document per operator input, plus the two the synthesizer publishes.
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


def is_current(key: str) -> bool:
    """Whether one stored object is something the product still writes.

    A key in a working area stays whatever it holds. Otherwise its first path segment says
    which set of file names applies, and its last says whether it is one of them. A first
    segment no set covers is a retired prefix -- ``csps/``, ``data-centers/`` -- and
    nothing under it is current.

    Public because it is the rule rather than a step: the post-deployment tier reads the
    live bucket and asks it of every key there, which is what says the prune actually ran.
    """
    if key.startswith(_WORKING_PREFIXES):
        return True
    prefix, _, rest = key.partition("/")
    kept = _KEPT_BY_PREFIX.get(prefix)
    if kept is None or not rest:
        return False
    return rest.rsplit("/", 1)[-1] in kept


def _stale_keys(client: Any, bucket: str) -> list[str]:
    """Every object in the store the product no longer writes, in key order.

    Listed a page at a time, because a listing answers with at most a thousand keys and a
    prune that stopped at the first page would leave the rest where they are and report
    that it had finished.
    """
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
    """Delete every stale object and name what went.

    The keys come back rather than a count, because the seed prints this into a job log and
    a number says nothing about whether the right things went. An empty list is the store
    already holding only what the product writes, which is what every run after the first
    should say.

    Each key is deleted by naming its version, because a delete that names none writes a
    delete marker over the key instead of removing it and the key goes on being listed
    behind that marker. The store's own lifecycle rule takes such markers away eventually,
    but eventually is a day, and a prune means remove.
    """
    bucket = os.environ["STORE_BUCKET"]
    deleted = _stale_keys(client, bucket)
    for key in deleted:
        client.delete_object(Bucket=bucket, Key=key, VersionId=_ONLY_VERSION)
    return {"deleted": deleted}


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Prune the store (POST), or say what would go without touching it (GET)."""
    client = _s3()
    if event.get("httpMethod") == "POST":
        return _response(200, _prune(client))
    return _response(200, {"stale": _stale_keys(client, os.environ["STORE_BUCKET"])})
