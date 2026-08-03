"""The client fixtures under test, declared here so this tier can ask for them.

A fixture is only exercised by being requested, and pytest finds the ones a directory may
request through its ``conftest.py``. Every tier that uses these declares them the same
way; this one differs only in that the fixtures are the subject rather than the setup.
"""
from __future__ import annotations

from test_fixtures.aws import (
    apigateway_client,
    config,
    dynamodb_client,
    ecr_client,
    events_client,
    iam_client,
    lambda_client,
    logs_client,
    s3_client,
    sns_client,
    sqs_client,
    state_bucket_name,
    sts_client,
)

__all__ = [
    "apigateway_client",
    "config",
    "dynamodb_client",
    "ecr_client",
    "events_client",
    "iam_client",
    "lambda_client",
    "logs_client",
    "s3_client",
    "sns_client",
    "sqs_client",
    "state_bucket_name",
    "sts_client",
]
