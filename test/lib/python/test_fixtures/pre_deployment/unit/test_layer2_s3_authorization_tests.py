from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from botocore.exceptions import ClientError

from test_fixtures.integration import create_layer2_s3_authorization_tests

_BUCKET = "10ulabs-terraform-state-us-east-2"


def _refusing_s3() -> Any:
    def head_bucket(**_kwargs: Any) -> dict[str, Any]:
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "HeadBucket")

    return SimpleNamespace(head_bucket=head_bucket)


def _layer() -> Any:
    return create_layer2_s3_authorization_tests()()


def test_a_permitted_look_at_the_state_bucket_passes() -> None:
    permitted = SimpleNamespace(head_bucket=lambda **_kwargs: {})
    assert _layer().test_can_call_s3_head_bucket(permitted, _BUCKET) is None


def test_a_denied_look_at_the_state_bucket_fails() -> None:
    with pytest.raises(pytest.fail.Exception, match=_BUCKET):
        _layer().test_can_call_s3_head_bucket(_refusing_s3(), _BUCKET)


def test_a_configured_bucket_name_passes() -> None:
    assert _layer().test_bucket_name_is_configured(_BUCKET) is None


def test_a_bucket_name_that_arrived_empty_fails() -> None:
    with pytest.raises(AssertionError):
        _layer().test_bucket_name_is_configured("")
