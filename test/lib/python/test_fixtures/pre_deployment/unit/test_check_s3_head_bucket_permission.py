from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from botocore.exceptions import ClientError

from test_fixtures.integration import check_s3_head_bucket_permission

_BUCKET = "10ulabs-terraform-state-us-east-2"


def _s3(code: str | None, asked: list[str]) -> Any:
    def head_bucket(**kwargs: Any) -> dict[str, Any]:
        asked.append(kwargs["Bucket"])
        if code is None:
            return {}
        raise ClientError({"Error": {"Code": code}}, "HeadBucket")

    return SimpleNamespace(head_bucket=head_bucket)


def _asked_about(code: str | None) -> list[str]:
    asked: list[str] = []
    check_s3_head_bucket_permission(_s3(code, asked), _BUCKET)
    return asked


def test_a_permitted_look_passes_the_layer() -> None:
    assert _asked_about(None) == [_BUCKET]


def test_a_bucket_that_is_not_there_passes_the_layer() -> None:
    assert _asked_about("404") == [_BUCKET]


def test_a_refusal_fails_the_layer_and_names_the_bucket() -> None:
    with pytest.raises(pytest.fail.Exception, match=_BUCKET):
        check_s3_head_bucket_permission(_s3("AccessDenied", []), _BUCKET)


def test_a_refusal_reported_as_a_status_fails_the_layer_too() -> None:
    with pytest.raises(pytest.fail.Exception, match="No permission to call s3:HeadBucket"):
        check_s3_head_bucket_permission(_s3("403", []), _BUCKET)


def test_an_error_that_is_neither_is_left_to_surface() -> None:
    with pytest.raises(ClientError):
        check_s3_head_bucket_permission(_s3("500", []), _BUCKET)
