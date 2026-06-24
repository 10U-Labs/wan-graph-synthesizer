"""Factories and helpers for pre-deployment integration tests.

These factories return pytest test *classes* (named ``Test...`` with
``test_...`` methods, exactly one assert per method) so that an endpoint's test
module can subclass or instantiate the shared coverage without duplicating it.

Usage::

    from test_fixtures.integration import create_simple_layer1_authentication_tests

    TestAuthentication = create_simple_layer1_authentication_tests()
"""
from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

NO_CREDENTIALS_MESSAGE = (
    "No AWS credentials found. Configure credentials via environment variables, "
    "~/.aws/credentials, or an IAM role."
)


def check_s3_head_bucket_permission(s3_client: Any, bucket_name: str) -> None:
    """Assert permission to call ``s3:HeadBucket`` on a bucket.

    A 403/AccessDenied means we lack permission and the test fails. A 404 means
    the bucket is absent but we are authorized, which is acceptable for an
    authorization-layer check.

    Args:
        s3_client: A boto3 S3 client.
        bucket_name: The bucket to probe.

    Raises:
        AssertionError: Via ``pytest.fail`` if access is denied.
        ClientError: Re-raised for error codes other than 403/AccessDenied/404.
    """
    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except ClientError as error:
        error_code = error.response["Error"]["Code"]
        if error_code in ("403", "AccessDenied"):
            pytest.fail(f"No permission to call s3:HeadBucket on '{bucket_name}'")
        if error_code != "404":
            raise


def create_simple_layer1_authentication_tests() -> type:
    """Create a Layer 1 authentication test class.

    The returned class verifies that valid AWS credentials exist by calling
    ``sts:GetCallerIdentity``. It expects an ``sts_client`` fixture.

    Returns:
        A pytest test class named ``TestAWSAuthentication``.
    """

    class TestAWSAuthentication:
        """Layer 1: verify AWS credentials are present and valid."""

        def test_aws_credentials_valid(self, sts_client: Any) -> None:
            """Verify credentials resolve to an account via STS."""
            response = sts_client.get_caller_identity()
            assert response["Account"] is not None

        def test_aws_credentials_not_expired(self, sts_client: Any) -> None:
            """Verify the STS identity response carries an ARN."""
            response = sts_client.get_caller_identity()
            assert "Arn" in response

    return TestAWSAuthentication


def create_layer2_s3_authorization_tests() -> type:
    """Create a Layer 2 S3 authorization test class.

    The returned class verifies permission to call ``s3:HeadBucket`` on the
    shared state bucket. It expects ``s3_client`` and ``state_bucket_name``
    fixtures.

    Returns:
        A pytest test class named ``TestS3Authorization``.
    """

    class TestS3Authorization:
        """Layer 2: verify S3 authorization against the state bucket."""

        def test_can_call_s3_head_bucket(
            self, s3_client: Any, state_bucket_name: str
        ) -> None:
            """Verify permission to call s3:HeadBucket on the state bucket."""
            check_s3_head_bucket_permission(s3_client, state_bucket_name)

        def test_bucket_name_is_configured(self, state_bucket_name: str) -> None:
            """Verify the state bucket name is configured."""
            assert state_bucket_name

    return TestS3Authorization
