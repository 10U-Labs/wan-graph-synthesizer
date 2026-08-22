from __future__ import annotations

from typing import Any, cast

import boto3
import pytest

from test_terraform_config import STATE_BUCKET, TEST_AWS_REGION, common_outputs


def _client(service: str) -> Any:
    return cast(Any, boto3).client(service, region_name=TEST_AWS_REGION)


@pytest.fixture(scope="session")
def config() -> dict[str, object]:
    return common_outputs()


@pytest.fixture(scope="session")
def state_bucket_name() -> str:
    return STATE_BUCKET


@pytest.fixture(scope="session")
def sts_client() -> Any:
    return _client("sts")


@pytest.fixture(scope="session")
def iam_client() -> Any:
    return _client("iam")


@pytest.fixture(scope="session")
def s3_client() -> Any:
    return _client("s3")


@pytest.fixture(scope="session")
def lambda_client() -> Any:
    return _client("lambda")


@pytest.fixture(scope="session")
def apigateway_client() -> Any:
    return _client("apigateway")


@pytest.fixture(scope="session")
def logs_client() -> Any:
    return _client("logs")


def get_log_group_info(client: Any, log_group_name: str) -> dict[str, object]:
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
