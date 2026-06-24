"""Boto3 client fixtures shared by the wan post-deployment tier.

The foundation (``test_fixtures.aws``) provides every client this tier needs
except ECS, so an ``ecs_client`` session fixture is defined here, built the same
way the foundation builds its clients (boto3 in the shared region).
"""
from __future__ import annotations

from typing import Any, cast

import boto3
import pytest

from test_fixtures.aws import (
    ecr_client,
    events_client,
    iam_client,
    lambda_client,
    logs_client,
)
from test_terraform_config import TEST_AWS_REGION

__all__ = [
    "ecr_client",
    "events_client",
    "iam_client",
    "lambda_client",
    "logs_client",
]


@pytest.fixture(name="ecs_client", scope="session")
def ecs_client_fixture() -> Any:
    """Create an ECS client in the shared region."""
    return cast(Any, boto3).client("ecs", region_name=TEST_AWS_REGION)
