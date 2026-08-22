from __future__ import annotations

import boto3
import pytest

import test_fixtures.aws
from test_terraform_config import STATE_BUCKET, TEST_AWS_REGION

_CLIENT_FIXTURES = [
    ("sts_client", "sts"),
    ("iam_client", "iam"),
    ("s3_client", "s3"),
    ("lambda_client", "lambda"),
    ("apigateway_client", "apigateway"),
    ("logs_client", "logs"),
]


def _built(service: str, region_name: str) -> tuple[str, str]:
    return service, region_name


@pytest.mark.parametrize(("fixture_name", "service"), _CLIENT_FIXTURES)
def test_each_client_fixture_builds_its_own_service_in_the_declared_region(
        fixture_name: str, service: str,
        request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(boto3, "client", _built)
    assert request.getfixturevalue(fixture_name) == (service, TEST_AWS_REGION)


def test_the_shared_configuration_offered_is_the_parsed_common_module(
        request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(test_fixtures.aws, "common_outputs", lambda: {"aws_region": "eu-west-1"})
    assert request.getfixturevalue("config") == {"aws_region": "eu-west-1"}


def test_the_state_bucket_offered_is_the_declared_one(request: pytest.FixtureRequest) -> None:
    assert request.getfixturevalue("state_bucket_name") == STATE_BUCKET
