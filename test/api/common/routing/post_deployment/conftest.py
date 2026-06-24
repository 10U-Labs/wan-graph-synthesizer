"""Boto3 client fixtures shared by the routing post-deployment tier."""
from __future__ import annotations

from test_fixtures.aws import apigateway_client

__all__ = ["apigateway_client"]
