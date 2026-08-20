"""Unit tests for the probe that asks AWS whether a named resource is there.

Nine deployable units run a state check before they deploy, and this probe is what that
check consults about each thing the plan would create. It answers ``True`` or ``False``,
and both answers are believed outright.

Each answer costs something different when it is wrong. Read as present, a resource that
is not there stops a deployment and reports a collision that does not exist. Read as
absent, a resource that is there lets the deployment run into it -- which is the failure
the state layer exists to prevent, and the reason an error from the platform must never be
folded into ``False``: a call that was refused or throttled has said nothing about whether
the resource is there.

Every service is replaced by a client that answers one way for every call, so what is
under test is the ten checkers and the two registries that path to them.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

import boto3
import pytest
from botocore.exceptions import ClientError

from test_terraform_config import TEST_AWS_REGION
from test_terraform_drift import RESOURCE_CHECKERS, RESOURCE_TO_CLIENT, check_resource_exists

_NAME = "wan-synthesizer-carriers"


class _Missing(Exception):
    """Stand-in for whichever not-found exception the service in question raises."""


# The call each checker makes, and the exception each one catches to read absence. Both are
# written out rather than answered for any name, so a checker that starts asking something
# else fails here instead of being answered by a double that agrees to anything.
_CALLS = (
    "get_function", "get_role", "describe_log_groups", "describe_table", "head_bucket",
    "get_queue_url", "get_topic_attributes", "get_parameter", "describe_rule", "get_rest_api",
)
_EXCEPTIONS = SimpleNamespace(
    ResourceNotFoundException=_Missing,
    NoSuchEntityException=_Missing,
    QueueDoesNotExist=_Missing,
    NotFoundException=_Missing,
    ParameterNotFound=_Missing,
)


def _client(answer: Callable[..., Any]) -> Any:
    """A client answering every call a checker makes the one way it was built to answer."""
    return SimpleNamespace(exceptions=_EXCEPTIONS, **{call: answer for call in _CALLS})


def _present(**_kwargs: Any) -> dict[str, Any]:
    """Answer the way a service answers about a resource it holds."""
    return {"logGroups": [{"logGroupName": _NAME}]}


def _missing(**_kwargs: Any) -> dict[str, Any]:
    """Refuse the way a service refuses a resource it does not hold."""
    raise _Missing()


def _no_log_group(**_kwargs: Any) -> dict[str, Any]:
    """Answer a prefix query with nothing, which is how CloudWatch reports absence."""
    return {"logGroups": []}


def _neighbouring_log_group(**_kwargs: Any) -> dict[str, Any]:
    """Answer a prefix query with a longer name, which is a different group."""
    return {"logGroups": [{"logGroupName": f"{_NAME}-merge"}]}


def _no_bucket(**_kwargs: Any) -> dict[str, Any]:
    """Refuse the way S3 refuses a bucket that is not there."""
    raise ClientError({"Error": {"Code": "404"}}, "HeadBucket")


def _denied(**_kwargs: Any) -> dict[str, Any]:
    """Refuse the way S3 refuses a caller that may not look at all."""
    raise ClientError({"Error": {"Code": "403"}}, "HeadBucket")


# The two services that report absence without raising the service's not-found exception.
_ABSENT: dict[str, Callable[..., Any]] = {
    "aws_cloudwatch_log_group": _no_log_group,
    "aws_s3_bucket": _no_bucket,
}


def _answering(monkeypatch: pytest.MonkeyPatch, answer: Callable[..., Any]) -> None:
    """Have every client built answer each call with *answer*."""
    monkeypatch.setattr(boto3, "client", lambda _service, **_kwargs: _client(answer))


def _asked(recorded: list[str], value: str) -> Any:
    """Record what a client was built for and answer every call as present."""
    recorded.append(value)
    return _client(_present)


@pytest.mark.parametrize("resource_type", sorted(RESOURCE_CHECKERS))
def test_a_resource_the_platform_answers_for_reads_present(
        resource_type: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each of the ten kinds is asked in the way its own service answers about it."""
    _answering(monkeypatch, _present)
    assert check_resource_exists(resource_type, _NAME) is True


@pytest.mark.parametrize("resource_type", sorted(RESOURCE_CHECKERS))
def test_a_resource_the_platform_does_not_hold_reads_absent(
        resource_type: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal naming the resource as unknown is an absence, and is reported as one."""
    _answering(monkeypatch, _ABSENT.get(resource_type, _missing))
    assert check_resource_exists(resource_type, _NAME) is False


def test_a_log_group_merely_sharing_the_prefix_is_not_the_one_asked_about(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """CloudWatch is asked by prefix, so every longer name comes back and none of them is it."""
    _answering(monkeypatch, _neighbouring_log_group)
    assert check_resource_exists("aws_cloudwatch_log_group", _NAME) is False


def test_an_error_that_says_nothing_about_absence_is_not_made_into_one(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A denied look leaves the question open, and a deployment must not proceed on it."""
    _answering(monkeypatch, _denied)
    with pytest.raises(ClientError):
        check_resource_exists("aws_s3_bucket", _NAME)


def test_a_kind_with_no_checker_is_refused_rather_than_answered() -> None:
    """Answering ``False`` for a kind nobody wrote a probe for would hide it from the layer."""
    with pytest.raises(ValueError, match="Unsupported resource type: aws_kinesis_stream"):
        check_resource_exists("aws_kinesis_stream", _NAME)


def test_the_refusal_says_what_can_be_asked_about() -> None:
    """Whoever added the resource needs to be told where to add the probe."""
    with pytest.raises(ValueError, match="Supported types: aws_s3_bucket"):
        check_resource_exists("aws_kinesis_stream", _NAME)


def test_the_service_asked_is_the_one_the_kind_belongs_to(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Lambda asked of the S3 client is answered about a bucket of that name, or not at all."""
    asked: list[str] = []
    monkeypatch.setattr(boto3, "client", lambda service, **_kwargs: _asked(asked, service))
    check_resource_exists("aws_lambda_function", _NAME)
    assert asked == ["lambda"]


def test_the_region_asked_in_is_the_declared_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """A probe run against another region reports every resource in this one absent."""
    asked: list[str] = []
    monkeypatch.setattr(boto3, "client", lambda _service, region_name: _asked(asked, region_name))
    check_resource_exists("aws_lambda_function", _NAME)
    assert asked == [TEST_AWS_REGION]


def test_a_region_the_caller_names_is_the_one_asked_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller checking another region says so, and is not quietly answered about this one."""
    asked: list[str] = []
    monkeypatch.setattr(boto3, "client", lambda _service, region_name: _asked(asked, region_name))
    check_resource_exists("aws_lambda_function", _NAME, region="eu-west-1")
    assert asked == ["eu-west-1"]


def test_every_kind_that_can_be_checked_names_a_service_to_ask() -> None:
    """A kind in one registry and not the other fails on a lookup rather than a probe."""
    assert sorted(RESOURCE_TO_CLIENT) == sorted(RESOURCE_CHECKERS)
