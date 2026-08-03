"""Unit tests for the stand-in clients a write-side case hands a handler.

A storing endpoint reaches two services: the store it writes into and Lambda, which it
invokes when a build is meant to start. Both are replaced here by one call, so a test can
read the store afterwards and can say whether anything was invoked.

The second is the assertion that would fail quietly. "A PUT starts no build" is judged on
an empty list of invocations, and a stand-in that never recorded one produces that empty
list whatever the handler did.
"""

from __future__ import annotations

from typing import Any

import pytest

from test_handler_contracts import write_clients


def test_the_store_written_into_is_the_one_the_case_can_read() -> None:
    """A write test judges the handler on the store afterwards, so both see one mapping."""
    objects: dict[str, bytes] = {}
    write_clients(objects, [])("s3").put_object(Key="carriers/zayo/vertices.json", Body=b"[]")
    assert objects == {"carriers/zayo/vertices.json": b"[]"}


def test_every_client_the_handler_builds_reaches_the_same_store() -> None:
    """A handler that rebuilds its client mid-request must not lose what it already wrote."""
    build = write_clients({}, [])
    build("s3").put_object(Key="tenants/daf/label.json", Body=b'{"name": "daf"}')
    stored = build("s3").get_object(Key="tenants/daf/label.json")
    assert stored["Body"].read() == b'{"name": "daf"}'


def test_an_invocation_reaches_the_list_the_case_reads() -> None:
    """Whether a build was started is read off this list and off nothing else."""
    invocations: list[dict[str, Any]] = []
    write_clients({}, invocations)("lambda").invoke(FunctionName="wan-graph-synthesizer-wan")
    assert invocations == [{"FunctionName": "wan-graph-synthesizer-wan"}]


def test_the_region_a_handler_asks_for_is_accepted() -> None:
    """Handlers name a region when they build a client, and the stand-in has no use for it."""
    build = write_clients({"carriers/zayo/vertices.json": b"[]"}, [])
    assert build("s3", region_name="us-east-2").list_objects_v2()["Contents"] == [
        {"Key": "carriers/zayo/vertices.json"}
    ]


def test_a_service_no_handler_uses_is_refused() -> None:
    """A handler reaching for something else is a change these cases have not been told about."""
    with pytest.raises(KeyError):
        write_clients({}, [])("dynamodb")
