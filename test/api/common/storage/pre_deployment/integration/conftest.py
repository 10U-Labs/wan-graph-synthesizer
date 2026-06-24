"""Boto3 fixtures for the storage pre-deployment integration tier.

The authentication and authorization layers need live AWS clients; these are
re-exported from the shared ``test_fixtures.aws`` plugin so pytest discovers
them without hardcoding a region or the state bucket name.
"""
from __future__ import annotations

from test_fixtures.aws import s3_client, state_bucket_name, sts_client

__all__ = ["s3_client", "state_bucket_name", "sts_client"]
