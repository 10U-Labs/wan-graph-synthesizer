"""Unit tests for loading an endpoint's handler the way its Lambda runs it.

Seven test files drive a deployed handler through this call, and it settles three things
before the first assertion is made: which file is loaded, what the environment says while
it runs, and whether the client the previous case cached is still in place. The third is
the one that fails silently -- a handler holding a client from an earlier case answers
from that case's store, so a test passes on data it never wrote.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from test_handler_contracts import load_handler
from test_s3_store_mock import fake_s3


def test_the_handler_loaded_is_the_endpoints_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every endpoint keeps its handler at the same path, so the name is what tells them apart."""
    assert load_handler("carriers", monkeypatch).__name__ == "carriers_handler"


def test_an_endpoint_below_another_is_named_by_its_whole_path(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A nested endpoint would otherwise be loaded under a name one of its parents holds."""
    assert load_handler("carriers/merge", monkeypatch).__name__ == "carriers_merge_handler"


def test_the_store_bucket_is_named_before_the_handler_reads_it(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A handler reads the bucket out of its environment, and unset it raises on the first call."""
    load_handler("carriers", monkeypatch)
    assert os.environ["STORE_BUCKET"] == "test-bucket"


def test_further_environment_a_case_needs_is_set_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """The WAN dispatcher reads the function it invokes out of its own environment."""
    load_handler(
        "tenants/wan", monkeypatch,
        SYNTHESIZER_FUNCTION_NAME="wan-graph-synthesizer-wan-synthesizer",
    )
    assert os.environ["SYNTHESIZER_FUNCTION_NAME"] == "wan-graph-synthesizer-wan-synthesizer"


def test_the_handler_starts_with_no_client_from_an_earlier_case(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The cache is cleared on the way in, so the next request builds a client of its own."""
    module = load_handler("carriers", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({}, keys=[])) as built:
        module.lambda_handler({}, None)
    assert built.call_count == 1
