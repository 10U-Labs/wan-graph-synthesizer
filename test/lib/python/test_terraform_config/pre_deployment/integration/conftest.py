"""Boto3 fixtures for the shared configuration module's integration tier.

One test here lists the live state bucket to hold what is stored against what the
stacks under ``src/`` declare, so this tier needs an S3 client. Every other test in
it reads only files on disk.
"""
from __future__ import annotations

from test_fixtures.aws import s3_client

__all__ = ["s3_client"]
