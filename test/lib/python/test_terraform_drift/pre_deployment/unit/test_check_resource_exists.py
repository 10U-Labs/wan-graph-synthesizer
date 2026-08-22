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
    pass


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
    return SimpleNamespace(exceptions=_EXCEPTIONS, **{call: answer for call in _CALLS})


def _present(**_kwargs: Any) -> dict[str, Any]:
    return {"logGroups": [{"logGroupName": _NAME}]}


def _missing(**_kwargs: Any) -> dict[str, Any]:
    raise _Missing()


def _no_log_group(**_kwargs: Any) -> dict[str, Any]:
    return {"logGroups": []}


def _neighbouring_log_group(**_kwargs: Any) -> dict[str, Any]:
    return {"logGroups": [{"logGroupName": f"{_NAME}-merge"}]}


def _no_bucket(**_kwargs: Any) -> dict[str, Any]:
    raise ClientError({"Error": {"Code": "404"}}, "HeadBucket")


def _denied(**_kwargs: Any) -> dict[str, Any]:
    raise ClientError({"Error": {"Code": "403"}}, "HeadBucket")


_ABSENT: dict[str, Callable[..., Any]] = {
    "aws_cloudwatch_log_group": _no_log_group,
    "aws_s3_bucket": _no_bucket,
}


def _answering(monkeypatch: pytest.MonkeyPatch, answer: Callable[..., Any]) -> None:
    monkeypatch.setattr(boto3, "client", lambda _service, **_kwargs: _client(answer))


def _asked(recorded: list[str], value: str) -> Any:
    recorded.append(value)
    return _client(_present)


@pytest.mark.parametrize("resource_type", sorted(RESOURCE_CHECKERS))
def test_a_resource_the_platform_answers_for_reads_present(
        resource_type: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _answering(monkeypatch, _present)
    assert check_resource_exists(resource_type, _NAME) is True


@pytest.mark.parametrize("resource_type", sorted(RESOURCE_CHECKERS))
def test_a_resource_the_platform_does_not_hold_reads_absent(
        resource_type: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _answering(monkeypatch, _ABSENT.get(resource_type, _missing))
    assert check_resource_exists(resource_type, _NAME) is False


def test_a_log_group_merely_sharing_the_prefix_is_not_the_one_asked_about(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _answering(monkeypatch, _neighbouring_log_group)
    assert check_resource_exists("aws_cloudwatch_log_group", _NAME) is False


def test_an_error_that_says_nothing_about_absence_is_not_made_into_one(
        monkeypatch: pytest.MonkeyPatch) -> None:
    _answering(monkeypatch, _denied)
    with pytest.raises(ClientError):
        check_resource_exists("aws_s3_bucket", _NAME)


def test_a_kind_with_no_checker_is_refused_rather_than_answered() -> None:
    with pytest.raises(ValueError, match="Unsupported resource type: aws_kinesis_stream"):
        check_resource_exists("aws_kinesis_stream", _NAME)


def test_the_refusal_says_what_can_be_asked_about() -> None:
    with pytest.raises(ValueError, match="Supported types: aws_s3_bucket"):
        check_resource_exists("aws_kinesis_stream", _NAME)


def test_the_service_asked_is_the_one_the_kind_belongs_to(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    monkeypatch.setattr(boto3, "client", lambda service, **_kwargs: _asked(asked, service))
    check_resource_exists("aws_lambda_function", _NAME)
    assert asked == ["lambda"]


def test_the_region_asked_in_is_the_declared_one(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    monkeypatch.setattr(boto3, "client", lambda _service, region_name: _asked(asked, region_name))
    check_resource_exists("aws_lambda_function", _NAME)
    assert asked == [TEST_AWS_REGION]


def test_a_region_the_caller_names_is_the_one_asked_in(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    monkeypatch.setattr(boto3, "client", lambda _service, region_name: _asked(asked, region_name))
    check_resource_exists("aws_lambda_function", _NAME, region="eu-west-1")
    assert asked == ["eu-west-1"]


def test_every_kind_that_can_be_checked_names_a_service_to_ask() -> None:
    assert sorted(RESOURCE_TO_CLIENT) == sorted(RESOURCE_CHECKERS)
