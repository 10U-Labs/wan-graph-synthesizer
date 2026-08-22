from __future__ import annotations

from typing import Any

import pytest

import test_terraform_config
from test_terraform_config import store_bucket_name


def _declared(monkeypatch: pytest.MonkeyPatch, resources: list[dict[str, Any]]) -> None:
    monkeypatch.setattr(
        test_terraform_config, "load_tf", lambda _path: {"resource": resources}
    )


def test_the_declared_bucket_name_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    _declared(monkeypatch, [{"aws_s3_bucket": {"store": {"bucket": "a-store"}}}])
    assert store_bucket_name() == "a-store"


def test_a_missing_store_resource_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _declared(monkeypatch, [{"aws_s3_bucket": {"other": {"bucket": "a-store"}}}])
    with pytest.raises(AssertionError):
        store_bucket_name()


def test_the_real_storage_stack_declares_a_store() -> None:
    assert store_bucket_name().endswith("-store-us-east-2")
