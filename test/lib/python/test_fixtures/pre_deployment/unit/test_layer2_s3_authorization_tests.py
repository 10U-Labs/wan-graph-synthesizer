"""Unit tests for the authorization layer every deployable unit takes rather than writes.

The layer below establishes that the credentials are valid; this one establishes that they
may read the shared OpenTofu state, which is the first thing any deployment here does.
Every unit takes the same two tests from this factory, so a class that passed whatever it
was given would report eleven pre-deployment tiers authorized when none of them were, and
each would fail during its own deployment instead.

The second of the two is small and worth having: a bucket name that arrived empty makes
the permission check ask about nothing at all and be answered, which reads as permission.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from botocore.exceptions import ClientError

from test_fixtures.integration import create_layer2_s3_authorization_tests

_BUCKET = "10ulabs-terraform-state-us-east-2"


def _refusing_s3() -> Any:
    """An S3 client that denies the look, the way it does for credentials without the grant."""

    def head_bucket(**_kwargs: Any) -> dict[str, Any]:
        """Refuse the call with the code IAM denies with."""
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "HeadBucket")

    return SimpleNamespace(head_bucket=head_bucket)


def _layer() -> Any:
    """The authorization tests as a unit under test rather than as tests to be collected."""
    return create_layer2_s3_authorization_tests()()


def test_a_permitted_look_at_the_state_bucket_passes() -> None:
    """Credentials that may read the shared state are what this layer is establishing."""
    permitted = SimpleNamespace(head_bucket=lambda **_kwargs: {})
    assert _layer().test_can_call_s3_head_bucket(permitted, _BUCKET) is None


def test_a_denied_look_at_the_state_bucket_fails() -> None:
    """A denial stops the unit here rather than part way through its own deployment."""
    with pytest.raises(pytest.fail.Exception, match=_BUCKET):
        _layer().test_can_call_s3_head_bucket(_refusing_s3(), _BUCKET)


def test_a_configured_bucket_name_passes() -> None:
    """A name to ask about is what the layer above it presumes."""
    assert _layer().test_bucket_name_is_configured(_BUCKET) is None


def test_a_bucket_name_that_arrived_empty_fails() -> None:
    """An empty name asks about nothing, and being answered about nothing is not permission."""
    with pytest.raises(AssertionError):
        _layer().test_bucket_name_is_configured("")
