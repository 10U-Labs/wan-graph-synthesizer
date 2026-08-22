from __future__ import annotations

from typing import Any

import pytest

from test_handler_contracts import write_clients


def test_the_store_written_into_is_the_one_the_case_can_read() -> None:
    objects: dict[str, bytes] = {}
    write_clients(objects, [])("s3").put_object(Key="carriers/zayo/pops.json", Body=b"[]")
    assert objects == {"carriers/zayo/pops.json": b"[]"}


def test_every_client_the_handler_builds_reaches_the_same_store() -> None:
    build = write_clients({}, [])
    build("s3").put_object(Key="tenants/daf/label.json", Body=b'{"name": "daf"}')
    stored = build("s3").get_object(Key="tenants/daf/label.json")
    assert stored["Body"].read() == b'{"name": "daf"}'


def test_an_invocation_reaches_the_list_the_case_reads() -> None:
    invocations: list[dict[str, Any]] = []
    write_clients({}, invocations)("lambda").invoke(FunctionName="wan-synthesizer-wan")
    assert invocations == [{"FunctionName": "wan-synthesizer-wan"}]


def test_the_region_a_handler_asks_for_is_accepted() -> None:
    build = write_clients({"carriers/zayo/pops.json": b"[]"}, [])
    assert build("s3", region_name="us-east-2").list_objects_v2()["Contents"] == [
        {"Key": "carriers/zayo/pops.json"}
    ]


def test_a_service_no_handler_uses_is_refused() -> None:
    with pytest.raises(KeyError):
        write_clients({}, [])("dynamodb")
