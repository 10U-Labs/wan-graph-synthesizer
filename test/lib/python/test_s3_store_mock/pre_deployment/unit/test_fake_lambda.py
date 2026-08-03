"""Unit tests for the stand-in Lambda client that records each invocation.

One endpoint starting another is the shape the write endpoints are held to: a PUT stores
a collection and invokes nothing, and a POST is what starts a build. Both readings rest
on this list, and a double that dropped an invocation would report a write endpoint as
well behaved precisely when it had started a build nobody asked for.
"""

from __future__ import annotations

from typing import Any

from test_s3_store_mock import fake_lambda


def test_the_invocation_made_is_the_one_recorded() -> None:
    """Which function was invoked, and with what, is what an invocation test reads."""
    invocations: list[dict[str, Any]] = []
    fake_lambda(invocations).invoke(FunctionName="wan-graph-synthesizer-wan", Payload=b"{}")
    assert invocations == [{"FunctionName": "wan-graph-synthesizer-wan", "Payload": b"{}"}]


def test_an_invocation_is_answered_as_an_accepted_asynchronous_call() -> None:
    """The endpoints invoke without waiting, and 202 is what the real client answers with."""
    assert fake_lambda([]).invoke(FunctionName="wan-graph-synthesizer-wan") == {"StatusCode": 202}


def test_a_caller_that_invokes_nothing_records_nothing() -> None:
    """The empty list is the assertion a write endpoint is held to, so it has to stay empty."""
    invocations: list[dict[str, Any]] = []
    fake_lambda(invocations)
    assert invocations == []
