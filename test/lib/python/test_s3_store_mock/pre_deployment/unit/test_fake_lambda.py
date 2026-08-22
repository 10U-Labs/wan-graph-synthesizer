from __future__ import annotations

from typing import Any

from test_s3_store_mock import fake_lambda


def test_the_invocation_made_is_the_one_recorded() -> None:
    invocations: list[dict[str, Any]] = []
    fake_lambda(invocations).invoke(FunctionName="wan-synthesizer-wan", Payload=b"{}")
    assert invocations == [{"FunctionName": "wan-synthesizer-wan", "Payload": b"{}"}]


def test_an_invocation_is_answered_as_an_accepted_asynchronous_call() -> None:
    assert fake_lambda([]).invoke(FunctionName="wan-synthesizer-wan") == {"StatusCode": 202}


def test_a_caller_that_invokes_nothing_records_nothing() -> None:
    invocations: list[dict[str, Any]] = []
    fake_lambda(invocations)
    assert len(invocations) == 0
