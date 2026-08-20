"""Unit tests for the store bucket name read off the storage stack.

Every endpoint's Lambda is handed this name as ``STORE_BUCKET``, and the post-deployment
tiers hold the live value against it. If the read answered the wrong name, or answered
quietly when the resource was gone, those tests would compare a live Lambda against a
bucket nobody declared and pass.
"""

from __future__ import annotations

from typing import Any

import pytest

import test_terraform_config
from test_terraform_config import store_bucket_name


def _declared(monkeypatch: pytest.MonkeyPatch, resources: list[dict[str, Any]]) -> None:
    """Have the storage stack declare ``resources`` and nothing else."""
    monkeypatch.setattr(
        test_terraform_config, "load_tf", lambda _path: {"resource": resources}
    )


def test_the_declared_bucket_name_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    """The name comes back off ``aws_s3_bucket.store``'s own ``bucket`` argument."""
    _declared(monkeypatch, [{"aws_s3_bucket": {"store": {"bucket": "a-store"}}}])
    assert store_bucket_name() == "a-store"


def test_a_missing_store_resource_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A storage stack declaring no store fails here rather than answering nothing."""
    _declared(monkeypatch, [{"aws_s3_bucket": {"other": {"bucket": "a-store"}}}])
    with pytest.raises(AssertionError):
        store_bucket_name()


def test_the_real_storage_stack_declares_a_store() -> None:
    """The name is read off the repository's own storage stack, not only a stand-in."""
    assert store_bucket_name().endswith("-store-us-east-2")
