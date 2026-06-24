"""Boto3 fixtures for the storage post-deployment integration tier.

These run against live AWS after the stack is reconciled, so they need an S3
client; the store bucket name comes from the stack-level conftest.
"""
from __future__ import annotations

from test_fixtures.aws import s3_client

__all__ = ["s3_client"]
