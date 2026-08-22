"""Session-scoped boto3 client fixtures and AWS helpers for pytest.

Enable in a test tree by adding to ``conftest.py``::

    pytest_plugins = ["test_fixtures.aws"]

Every client is built for the region declared in the shared OpenTofu common
module (via ``test_terraform_config.TEST_AWS_REGION``), so tests never hardcode
a region.
"""
from __future__ import annotations

from typing import Any, cast

import boto3
import pytest

from test_terraform_config import STATE_BUCKET, TEST_AWS_REGION, common_outputs


def _client(service: str) -> Any:
    """Build a boto3 client for ``service`` in the shared region."""
    return cast(Any, boto3).client(service, region_name=TEST_AWS_REGION)


@pytest.fixture(scope="session")
def config() -> dict[str, object]:
    """Provide the parsed shared common outputs."""
    return common_outputs()


@pytest.fixture(scope="session")
def state_bucket_name() -> str:
    """Provide the shared OpenTofu state bucket name."""
    return STATE_BUCKET


@pytest.fixture(scope="session")
def sts_client() -> Any:
    """Create an STS client."""
    return _client("sts")


@pytest.fixture(scope="session")
def iam_client() -> Any:
    """Create an IAM client."""
    return _client("iam")


@pytest.fixture(scope="session")
def s3_client() -> Any:
    """Create an S3 client."""
    return _client("s3")


@pytest.fixture(scope="session")
def lambda_client() -> Any:
    """Create a Lambda client."""
    return _client("lambda")


@pytest.fixture(scope="session")
def apigateway_client() -> Any:
    """Create an API Gateway client."""
    return _client("apigateway")


@pytest.fixture(scope="session")
def logs_client() -> Any:
    """Create a CloudWatch Logs client."""
    return _client("logs")


def get_log_group_info(client: Any, log_group_name: str) -> dict[str, object]:
    """Return existence and retention info for a CloudWatch log group.

    Args:
        client: A CloudWatch Logs boto3 client.
        log_group_name: Full log group name (e.g. ``/aws/lambda/MyFunction``).

    Returns:
        A dict with keys ``name``, ``exists``, and ``retention``.
    """
    response = client.describe_log_groups(logGroupNamePrefix=log_group_name, limit=1)
    matching = [
        group
        for group in response.get("logGroups", [])
        if group["logGroupName"] == log_group_name
    ]
    return {
        "name": log_group_name,
        "exists": len(matching) > 0,
        "retention": matching[0].get("retentionInDays") if matching else None,
    }
