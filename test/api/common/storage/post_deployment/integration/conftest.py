"""Boto3 fixtures for the storage post-deployment integration tier.

These run against live AWS after the stack is reconciled, so they need an S3
client; the store bucket name comes from the stack-level conftest. The Lambda
client is here for the one test that asks which functions in the account still
hold a role granting access to the store.
"""
from __future__ import annotations

from test_fixtures.aws import lambda_client, s3_client

__all__ = ["lambda_client", "s3_client"]
