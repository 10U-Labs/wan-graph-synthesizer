"""Unit tests for the boto3 clients every tier that talks to AWS is handed.

Fifty-one test files reach the platform through these fixtures, and each one decides two
things a test can never see for itself: which service is asked, and which region it is
asked in. A client built for the wrong region reaches a real account, is answered
truthfully, and reports every resource in it absent -- so the run names the resource, the
deployment that owns it, and never the fixture.

``boto3.client`` is replaced here by something that reports what it was asked to build,
so what is under test is the asking rather than anything AWS would answer.
"""

from __future__ import annotations

import boto3
import pytest

import test_fixtures.aws
from test_terraform_config import STATE_BUCKET, TEST_AWS_REGION

# Each client fixture beside the AWS service it is meant to build.
_CLIENT_FIXTURES = [
    ("sts_client", "sts"),
    ("iam_client", "iam"),
    ("s3_client", "s3"),
    ("lambda_client", "lambda"),
    ("apigateway_client", "apigateway"),
    ("logs_client", "logs"),
    ("dynamodb_client", "dynamodb"),
    ("sqs_client", "sqs"),
    ("sns_client", "sns"),
    ("events_client", "events"),
    ("ecr_client", "ecr"),
]


def _built(service: str, region_name: str) -> tuple[str, str]:
    """Stand in for ``boto3.client``, reporting what it was asked to build."""
    return service, region_name


@pytest.mark.parametrize(("fixture_name", "service"), _CLIENT_FIXTURES)
def test_each_client_fixture_builds_its_own_service_in_the_declared_region(
        fixture_name: str, service: str,
        request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """One fixture per service, and every one of them in the region the declaration names."""
    monkeypatch.setattr(boto3, "client", _built)
    assert request.getfixturevalue(fixture_name) == (service, TEST_AWS_REGION)


def test_the_shared_configuration_offered_is_the_parsed_common_module(
        request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The outputs are parsed once and handed on, rather than each tier reading the file."""
    monkeypatch.setattr(test_fixtures.aws, "common_outputs", lambda: {"aws_region": "eu-west-1"})
    assert request.getfixturevalue("config") == {"aws_region": "eu-west-1"}


def test_the_state_bucket_offered_is_the_declared_one(request: pytest.FixtureRequest) -> None:
    """The authorization layer proves it may read this bucket, so it has to be that bucket."""
    assert request.getfixturevalue("state_bucket_name") == STATE_BUCKET
