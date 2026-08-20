"""Unit tests for the store's prune endpoint Lambda handler.

The prune takes out every object stored under a name the product no longer writes, which
is what a rename leaves behind. What it must never take out is what the product does
write, so most of these cases are about what survives: a leftover deleted costs a re-seed,
a live collection deleted costs whatever nothing else holds a copy of.

The keys here are the shapes the live store actually holds -- a carrier's two files, the
merge's two, the provider regions, a tenant's inputs and published WAN, the two working
areas, and a prefix whose endpoint was deleted.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from test_s3_store_mock import fake_s3

_CURRENT = [
    "carriers/lumen/pops.json",
    "carriers/lumen/fiber-segments.json",
    "carriers/merge/pops.json",
    "carriers/merge/fiber-segments.json",
    "providers/regions.json",
    "tenants/daf/locations.json",
    "tenants/daf/wan.json",
    "tenants/daf/wan-status.json",
    "source/carriers/lumen.csv",
    "builds/daf/2026-08-20/graph.json",
]
_STALE = [
    "carriers/lumen/vertices.json",
    "carriers/lumen/edges.json",
    "carriers/merge/edges.json",
    "providers/vertices.json",
    "tenants/daf/csp-regions.json",
    "tenants/daf/forced-connections.json",
    "csps/aws/vertices.json",
    "data-centers/equinix/facilities.json",
]


def _store() -> dict[str, bytes]:
    """A store holding both what the product writes today and what renames left behind."""
    return {key: b"[]" for key in _CURRENT + _STALE}


def _prune(handler: Any, objects: dict[str, bytes]) -> Any:
    """POST the prune against a store holding ``objects``, and return its parsed body."""
    with patch("boto3.client", return_value=fake_s3(objects)):
        response = handler.lambda_handler({"httpMethod": "POST"}, None)
    return json.loads(response["body"])


def test_the_prune_deletes_every_stale_object(prune_handler: Any) -> None:
    """Every key stored under a name the product no longer writes is named as deleted."""
    assert _prune(prune_handler, _store())["deleted"] == sorted(_STALE)


def test_the_prune_leaves_every_current_object_where_it_is(prune_handler: Any) -> None:
    """Nothing the product writes today is taken out, which is the half that must not fail."""
    objects = _store()
    _prune(prune_handler, objects)
    assert sorted(objects) == sorted(_CURRENT)


def test_the_prune_leaves_the_working_areas_alone(prune_handler: Any) -> None:
    """source/ holds the pushed inputs and builds/ the artifacts the bucket expires itself."""
    objects = {"source/anything.csv": b"", "builds/whatever/scratch.json": b""}
    assert _prune(prune_handler, objects)["deleted"] == []


def test_the_prune_takes_out_a_prefix_whose_endpoint_was_deleted(prune_handler: Any) -> None:
    """csps/ and data-centers/ have no endpoint to reach them, so nothing under them is current."""
    objects = {"csps/aws/vertices.json": b"", "data-centers/qts/facilities.json": b""}
    assert _prune(prune_handler, objects)["deleted"] == sorted(objects)


def test_the_prune_takes_out_a_bare_prefix_marker(prune_handler: Any) -> None:
    """A zero-byte folder marker is not a collection the product writes."""
    assert _prune(prune_handler, {"carriers/": b""})["deleted"] == ["carriers/"]


def test_a_second_prune_finds_nothing_left_to_do(prune_handler: Any) -> None:
    """Running it twice is running it once: every later seed reports an empty list."""
    objects = _store()
    _prune(prune_handler, objects)
    assert _prune(prune_handler, objects)["deleted"] == []


def test_the_prune_reads_every_page_of_the_listing(prune_handler: Any) -> None:
    """A listing answers a thousand keys at a time, and the rest must not survive by luck."""
    pages = [
        {"Contents": [{"Key": "csps/aws/vertices.json"}],
         "IsTruncated": True, "NextContinuationToken": "more"},
        {"Contents": [{"Key": "csps/azure/vertices.json"}], "IsTruncated": False},
    ]
    fake = fake_s3({})
    fake.list_objects_v2 = lambda **kwargs: pages[1 if kwargs.get("ContinuationToken") else 0]
    with patch("boto3.client", return_value=fake):
        response = prune_handler.lambda_handler({"httpMethod": "POST"}, None)
    assert json.loads(response["body"])["deleted"] == [
        "csps/aws/vertices.json", "csps/azure/vertices.json",
    ]


def test_a_get_says_what_would_go_without_deleting_it(prune_handler: Any) -> None:
    """The read is how an operator sees the list before anything is taken out."""
    objects = _store()
    with patch("boto3.client", return_value=fake_s3(objects)):
        prune_handler.lambda_handler({"httpMethod": "GET"}, None)
    assert sorted(objects) == sorted(_CURRENT + _STALE)


def test_a_get_names_the_same_keys_the_prune_would_delete(prune_handler: Any) -> None:
    """What the read reports and what the write takes out are the same list."""
    with patch("boto3.client", return_value=fake_s3(_store())):
        response = prune_handler.lambda_handler({"httpMethod": "GET"}, None)
    assert json.loads(response["body"])["stale"] == sorted(_STALE)
