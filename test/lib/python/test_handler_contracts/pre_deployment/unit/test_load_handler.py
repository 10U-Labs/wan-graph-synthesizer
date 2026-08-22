from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from test_handler_contracts import load_handler
from test_s3_store_mock import fake_s3


def test_the_handler_loaded_is_the_endpoints_own(monkeypatch: pytest.MonkeyPatch) -> None:
    assert load_handler("carriers", monkeypatch).__name__ == "carriers_handler"


def test_an_endpoint_below_another_is_named_by_its_whole_path(
        monkeypatch: pytest.MonkeyPatch) -> None:
    assert load_handler("carriers/merge", monkeypatch).__name__ == "carriers_merge_handler"


def test_the_store_bucket_is_named_before_the_handler_reads_it(
        monkeypatch: pytest.MonkeyPatch) -> None:
    load_handler("carriers", monkeypatch)
    assert os.environ["STORE_BUCKET"] == "test-bucket"


def test_further_environment_a_case_needs_is_set_too(monkeypatch: pytest.MonkeyPatch) -> None:
    load_handler(
        "tenants/wan", monkeypatch,
        SYNTHESIZER_FUNCTION_NAME="wan-synthesizer-wan-synthesizer",
    )
    assert os.environ["SYNTHESIZER_FUNCTION_NAME"] == "wan-synthesizer-wan-synthesizer"


def test_the_handler_starts_with_no_client_from_an_earlier_case(
        monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_handler("carriers", monkeypatch)
    with patch("boto3.client", return_value=fake_s3({}, keys=[])) as built:
        module.lambda_handler({}, None)
    assert built.call_count == 1
