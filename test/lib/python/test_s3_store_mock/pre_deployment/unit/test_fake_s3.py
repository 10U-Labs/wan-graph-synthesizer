"""Unit tests for the stand-in S3 client every handler's unit tests store through.

The handlers keep the whole program's state in one bucket, so their unit tests need
something that behaves like that bucket: a read serves what a write left, a read of a key
nobody wrote raises what the real client raises, and a listing says which keys are there.
This double is that bucket for five test files.

A double that answers success to everything is the failure worth spelling out. A handler
that never wrote what it claimed to write passes every assertion made about its response,
because the only witness to the write is the double, and the run names nothing.
"""

from __future__ import annotations

import pytest

from test_s3_store_mock import NoSuchKey, fake_s3


def test_a_stored_object_reads_back_as_it_was_stored() -> None:
    """A canned object is served whole, which is what a handler parses its answer out of."""
    client = fake_s3({"carriers/lumen/vertices.json": b'[{"id": "P0"}]'})
    served = client.get_object(Key="carriers/lumen/vertices.json")
    assert served["Body"].read() == b'[{"id": "P0"}]'


def test_a_key_nobody_stored_raises_what_the_real_client_raises() -> None:
    """The handlers answer 404 by catching this, so the absence has to arrive as this error."""
    client = fake_s3({})
    with pytest.raises(NoSuchKey):
        client.get_object(Key="carriers/lumen/vertices.json")


def test_the_error_the_handlers_catch_is_the_error_the_double_raises() -> None:
    """A handler catches ``client.exceptions.NoSuchKey``, so the two have to be one class."""
    assert fake_s3({}).exceptions.NoSuchKey is NoSuchKey


def test_a_written_object_is_readable_afterwards() -> None:
    """A PUT then a GET is the journey a write-side test makes, and it stays in one store."""
    client = fake_s3({})
    client.put_object(Key="tenants/daf/label.json", Body=b'{"name": "daf"}')
    assert client.get_object(Key="tenants/daf/label.json")["Body"].read() == b'{"name": "daf"}'


def test_a_write_replaces_what_was_there() -> None:
    """Every write endpoint replaces a collection rather than adding to it."""
    objects = {"tenants/daf/label.json": b'{"name": "stale"}'}
    fake_s3(objects).put_object(Key="tenants/daf/label.json", Body=b'{"name": "daf"}')
    assert objects["tenants/daf/label.json"] == b'{"name": "daf"}'


def test_a_write_is_answered_the_way_the_real_client_answers() -> None:
    """Handlers read nothing off the reply, so an empty one is what the real call gives back."""
    assert fake_s3({}).put_object(Key="tenants/daf/label.json", Body=b"{}") == {}


def test_a_deleted_object_is_gone_from_the_store() -> None:
    """A DELETE endpoint is judged on the store afterwards, so the removal has to be real."""
    objects = {"tenants/daf/label.json": b"{}"}
    fake_s3(objects).delete_object(Key="tenants/daf/label.json")
    assert objects == {}


def test_deleting_a_key_that_is_not_there_is_not_an_error() -> None:
    """The real call is idempotent, so a handler deleting twice is not a failure."""
    assert fake_s3({}).delete_object(Key="tenants/daf/label.json") == {}


def test_the_listing_is_the_keys_the_store_holds() -> None:
    """A collection-root GET is answered from this listing, so it has to follow the writes."""
    client = fake_s3({"carriers/lumen/vertices.json": b"[]", "carriers/zayo/vertices.json": b"[]"})
    assert client.list_objects_v2(Bucket="store")["Contents"] == [
        {"Key": "carriers/lumen/vertices.json"},
        {"Key": "carriers/zayo/vertices.json"},
    ]


def test_a_listing_given_outright_is_the_one_served() -> None:
    """A listing test needs keys without bodies, so the caller may state the listing instead."""
    client = fake_s3({}, keys=["carriers/lumen/vertices.json"])
    assert client.list_objects_v2(Bucket="store")["Contents"] == [
        {"Key": "carriers/lumen/vertices.json"}
    ]


def test_a_listing_given_as_empty_is_served_empty() -> None:
    """An empty listing is a case in its own right and not the absence of one."""
    client = fake_s3({"carriers/lumen/vertices.json": b"[]"}, keys=[])
    assert client.list_objects_v2(Bucket="store")["Contents"] == []
