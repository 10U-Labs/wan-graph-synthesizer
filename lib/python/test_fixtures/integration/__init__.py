from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

NO_CREDENTIALS_MESSAGE = (
    "No AWS credentials found. Configure credentials via environment variables, "
    "~/.aws/credentials, or an IAM role."
)


def check_s3_head_bucket_permission(s3_client: Any, bucket_name: str) -> None:
    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except ClientError as error:
        error_code = error.response["Error"]["Code"]
        if error_code in ("403", "AccessDenied"):
            pytest.fail(f"No permission to call s3:HeadBucket on '{bucket_name}'")
        if error_code != "404":
            raise


def create_simple_layer1_authentication_tests() -> type:
    class TestAWSAuthentication:
        def test_aws_credentials_valid(self, sts_client: Any) -> None:
            response = sts_client.get_caller_identity()
            assert response["Account"] is not None

        def test_aws_credentials_not_expired(self, sts_client: Any) -> None:
            response = sts_client.get_caller_identity()
            assert "Arn" in response

    return TestAWSAuthentication


def create_layer2_s3_authorization_tests() -> type:
    class TestS3Authorization:
        def test_can_call_s3_head_bucket(
            self, s3_client: Any, state_bucket_name: str
        ) -> None:
            check_s3_head_bucket_permission(s3_client, state_bucket_name)

        def test_bucket_name_is_configured(self, state_bucket_name: str) -> None:
            assert state_bucket_name

    return TestS3Authorization
