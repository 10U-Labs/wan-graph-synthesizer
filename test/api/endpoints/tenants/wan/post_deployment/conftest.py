"""Boto3 client fixtures shared by the wan post-deployment tier.

The foundation (``test_fixtures.aws``) provides every client this tier needs -- the
dispatcher and worker are both plain Lambdas reached through the IAM, Lambda and
CloudWatch Logs clients.
"""
from __future__ import annotations

from test_fixtures.aws import (
    iam_client,
    lambda_client,
    logs_client,
)

__all__ = [
    "iam_client",
    "lambda_client",
    "logs_client",
]
