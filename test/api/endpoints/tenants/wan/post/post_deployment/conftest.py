"""Boto3 client fixtures shared by the synthesizer post-deployment tier.

The foundation (``test_fixtures.aws``) provides every client this tier needs -- the
synthesizer is a plain Lambda reached through the IAM, Lambda and CloudWatch Logs clients.
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
