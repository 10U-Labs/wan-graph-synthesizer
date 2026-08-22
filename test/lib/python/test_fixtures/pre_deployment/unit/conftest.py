from __future__ import annotations

from test_fixtures.aws import (
    apigateway_client,
    config,
    iam_client,
    lambda_client,
    logs_client,
    s3_client,
    state_bucket_name,
    sts_client,
)

__all__ = [
    "apigateway_client",
    "config",
    "iam_client",
    "lambda_client",
    "logs_client",
    "s3_client",
    "state_bucket_name",
    "sts_client",
]
