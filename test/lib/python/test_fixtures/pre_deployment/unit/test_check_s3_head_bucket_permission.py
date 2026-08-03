"""Unit tests for the check that credentials may inspect the shared state bucket.

This is the authorization layer of every deployable unit in the repository: before a
deployment reads the OpenTofu state it shares with the others, its tests establish that
the credentials are allowed to look. The check has to keep two answers apart that arrive
by the same route. A refusal means the credentials may not look, and the deployment would
fail; a not-found means they may look and the bucket is not there, which is somebody
else's business and not a reason to stop.

Getting that the wrong way round costs a deployment either way: treating a refusal as
absence lets a run start that cannot finish, and treating absence as a refusal stops a run
that would have been fine.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from botocore.exceptions import ClientError

from test_fixtures.integration import check_s3_head_bucket_permission

_BUCKET = "10ulabs-terraform-state-us-east-2"


def _s3(code: str | None = None) -> Any:
    """An S3 client answering ``head_bucket`` with the error code given, or allowing it."""

    def head_bucket(**_kwargs: Any) -> dict[str, Any]:
        """Allow the call, or refuse it the way the real client refuses."""
        if code is None:
            return {}
        raise ClientError({"Error": {"Code": code}}, "HeadBucket")

    return SimpleNamespace(head_bucket=head_bucket)


def test_a_permitted_look_passes_the_layer() -> None:
    """Credentials that may inspect the bucket are what this layer is establishing."""
    assert check_s3_head_bucket_permission(_s3(), _BUCKET) is None


def test_a_bucket_that_is_not_there_passes_the_layer() -> None:
    """A not-found says the call was allowed, and absence belongs to a later layer."""
    assert check_s3_head_bucket_permission(_s3("404"), _BUCKET) is None


def test_a_refusal_fails_the_layer_and_names_the_bucket() -> None:
    """A failure has to say which bucket could not be read, or nobody can act on it."""
    with pytest.raises(pytest.fail.Exception, match=_BUCKET):
        check_s3_head_bucket_permission(_s3("AccessDenied"), _BUCKET)


def test_a_refusal_reported_as_a_status_fails_the_layer_too() -> None:
    """The same denial arrives as ``403`` from some callers, and means the same thing."""
    with pytest.raises(pytest.fail.Exception, match="No permission to call s3:HeadBucket"):
        check_s3_head_bucket_permission(_s3("403"), _BUCKET)


def test_an_error_that_is_neither_is_left_to_surface() -> None:
    """A throttle or an outage is not an answer about permission, so it is not made into one."""
    with pytest.raises(ClientError):
        check_s3_head_bucket_permission(_s3("500"), _BUCKET)
