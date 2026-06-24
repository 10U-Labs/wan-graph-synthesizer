"""Boto3 fixtures for the carriers pre-deployment integration tier."""
from __future__ import annotations

from test_fixtures.aws import s3_client, state_bucket_name, sts_client

__all__ = ["s3_client", "state_bucket_name", "sts_client"]
