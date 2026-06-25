"""Boto3 client fixtures shared by the data-centers post-deployment tier."""
from __future__ import annotations

from test_fixtures.aws import iam_client, lambda_client, logs_client

__all__ = ["iam_client", "lambda_client", "logs_client"]
